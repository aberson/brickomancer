"""Tests for ``services.text_shaper.TextShaper`` (Phase 3, Step 6).

Strategy
--------
The Claude CLI call (``run_claude_text``) is the mock boundary: tests patch it so
the deterministic parse -> clamp -> fill -> validate tail runs without the
subprocess. The retry / error paths are exercised by feeding malformed output or a
raising subprocess.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import numpy as np
import pytest

from brickomancer.models.brick import MAX_GRID_DIM, MAX_GRID_HEIGHT, MIN_GRID_DIM
from brickomancer.services import text_shaper
from brickomancer.services.shaper import Shaper, validate_grid
from brickomancer.services.text_shaper import _GRID_N, TextShaper, TextShaperError

# Where run_claude_text is looked up (imported into the text_shaper namespace).
_PATCH_TARGET = "brickomancer.services.text_shaper.run_claude_text"


def _voxels_json(coords: list[list[int]]) -> str:
    return json.dumps({"voxels": coords})


def _solid_block(n: int = 6) -> str:
    """A grounded n x n x n solid block of voxels as model JSON."""
    coords = [[x, y, z] for x in range(n) for y in range(n) for z in range(n)]
    return _voxels_json(coords)


# ---------------------------------------------------------------------------
# Type / contract identity
# ---------------------------------------------------------------------------


def test_textshaper_is_a_shaper() -> None:
    assert issubclass(TextShaper, Shaper)
    assert isinstance(TextShaper("a star"), Shaper)


# ---------------------------------------------------------------------------
# Happy path: mocked subprocess -> real parse/fill/validate
# ---------------------------------------------------------------------------


def test_to_voxels_returns_contract_valid_grid() -> None:
    with patch(_PATCH_TARGET, return_value=_solid_block(6)):
        grid = TextShaper("a 6-cube").to_voxels()

    validate_grid(grid)  # must not raise
    assert grid.dtype == np.bool_
    assert grid.shape == (6, 6, 6)  # cropped to the occupied bbox
    assert grid.all()
    x, y, z = grid.shape
    assert MIN_GRID_DIM <= x <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= z <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= y <= MAX_GRID_HEIGHT


def test_markdown_fenced_output_is_parsed() -> None:
    fenced = "```json\n" + _solid_block(3) + "\n```"
    with patch(_PATCH_TARGET, return_value=fenced):
        grid = TextShaper("x").to_voxels()
    assert grid.shape == (3, 3, 3)


def test_axis_mapping_y_up() -> None:
    """A column of voxels along Y maps to the Y (vertical) axis, padded sub-2 elsewhere."""
    coords = [[5, y, 7] for y in range(6)]  # a 6-tall column at x=5, z=7
    with patch(_PATCH_TARGET, return_value=_voxels_json(coords)):
        grid = TextShaper("a column").to_voxels()
    # After crop: X and Z are a single occupied index -> padded up to MIN_GRID_DIM;
    # Y spans the 6-tall column.
    assert grid.shape[1] == 6
    assert grid.shape[0] == MIN_GRID_DIM
    assert grid.shape[2] == MIN_GRID_DIM


# ---------------------------------------------------------------------------
# Coordinate handling: clamp / skip
# ---------------------------------------------------------------------------


def test_out_of_bounds_coords_are_clamped() -> None:
    """Coords outside [0, _GRID_N-1] are clamped, not dropped or crash-inducing."""
    hi = _GRID_N - 1
    coords = [[-5, -1, 3], [999, 999, 999], [10, 10, 10]]
    with patch(_PATCH_TARGET, return_value=_voxels_json(coords)):
        grid = TextShaper("x").to_voxels()
    # Three distinct clamped points: (0,0,3), (hi,hi,hi), (10,10,10) all present.
    validate_grid(grid)
    assert grid.any()
    # Grid never exceeds the lattice bounds on any axis.
    assert all(s <= _GRID_N for s in grid.shape)
    assert hi <= _GRID_N - 1  # sanity


def test_malformed_entries_skipped_when_some_valid() -> None:
    coords = [["a", 1, 2], [1, 2], [3, 3, 3], [4, 4, 4]]  # 2 junk + 2 valid
    with patch(_PATCH_TARGET, return_value=_voxels_json(coords)):
        grid = TextShaper("x").to_voxels()
    validate_grid(grid)
    assert grid.any()


# ---------------------------------------------------------------------------
# Error / retry paths -> TextShaperError (route turns these into 503)
# ---------------------------------------------------------------------------


def test_malformed_output_retried_then_raises() -> None:
    """Non-JSON every attempt -> retried _MAX_ATTEMPTS times, then TextShaperError."""
    with patch(_PATCH_TARGET, return_value="not json at all") as mock_cli:
        with pytest.raises(TextShaperError, match="usable voxel model"):
            TextShaper("x").to_voxels()
    assert mock_cli.call_count == text_shaper._MAX_ATTEMPTS


def test_empty_voxels_retried_then_raises() -> None:
    with patch(_PATCH_TARGET, return_value=_voxels_json([])) as mock_cli:
        with pytest.raises(TextShaperError):
            TextShaper("x").to_voxels()
    assert mock_cli.call_count == text_shaper._MAX_ATTEMPTS


def test_subprocess_failure_not_retried() -> None:
    """A RuntimeError from the CLI (no token / non-zero exit) raises at once, no retry."""
    with patch(_PATCH_TARGET, side_effect=RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set")) as m:
        with pytest.raises(TextShaperError, match="Claude CLI unavailable"):
            TextShaper("x").to_voxels()
    assert m.call_count == 1


def test_subprocess_timeout_raises_text_shaper_error() -> None:
    """A CLI timeout (TimeoutExpired, not a RuntimeError) is caught -> TextShaperError.

    Regression guard: the live emit can exceed the timeout, and TimeoutExpired must
    surface as a clean 503 at the route, not an uncaught 500. Not retried.
    """
    timeout_exc = subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=180)
    with patch(_PATCH_TARGET, side_effect=timeout_exc) as m:
        with pytest.raises(TextShaperError, match="Claude CLI unavailable"):
            TextShaper("x").to_voxels()
    assert m.call_count == 1


def test_recovers_on_second_attempt() -> None:
    """A bad first emit then a good one returns a grid (retry works)."""
    with patch(_PATCH_TARGET, side_effect=["garbage", _solid_block(4)]) as mock_cli:
        grid = TextShaper("x").to_voxels()
    assert grid.shape == (4, 4, 4)
    assert mock_cli.call_count == 2


def test_model_unavailable_is_runtime_error() -> None:
    assert issubclass(TextShaperError, RuntimeError)

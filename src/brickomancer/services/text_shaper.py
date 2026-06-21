"""Text ``Shaper``: a description -> a voxel grid via a Claude CLI emit.

Phase 3, Step 6. The text counterpart of ``ImageShaper``. Instead of an image->3D
model, a Claude CLI subprocess emits a SPARSE voxel occupancy (a list of occupied
integer coordinates in a fixed cubic lattice, strict JSON) which we fill into the
shared ``(X, Y, Z)`` grid behind the same ``Shaper`` seam. Everything downstream
(connectivity-graph packer, LDraw writer, render) is identical to the image path.

Pipeline:

    claude -p (sparse-occupancy prompt)  ->  parse strict JSON {"voxels": [[x,y,z]...]}
    ->  clamp coords into the lattice  ->  fill dense grid  ->  crop to occupied bbox
    ->  edge-pad sub-MIN axes  ->  validate_grid

Graceful degradation
--------------------
Malformed / empty model output is retried (``_MAX_ATTEMPTS`` total, matching
``piece_detector``); a subprocess failure (no ``CLAUDE_CODE_OAUTH_TOKEN``,
non-zero exit) is NOT retried. Exhausting retries or a subprocess failure raises
:class:`TextShaperError` (a ``RuntimeError``) so the production route can return a
clean 503 instead of a 500.

The lattice is a fixed ``_GRID_N**3`` (no resolution arg) -- the seam docstring's
``TextShaper(description).to_voxels()`` form. Color is defaulted by the route (the
seam is geometry-only); a text description carries no source image to sample.
"""

from __future__ import annotations

import json
import re
import subprocess

import numpy as np

from brickomancer.models.brick import MIN_GRID_DIM
from brickomancer.services.shaper import Shaper, VoxelGrid, validate_grid
from brickomancer.utils.subprocess_utils import run_claude_text

__all__ = ["TextShaper", "TextShaperError"]

#: Edge length of the cubic occupancy lattice the model emits into (Y-up). 20**3
#: is well within the grid contract (footprint <= MAX_GRID_DIM, height <= MAX_GRID_HEIGHT).
_GRID_N = 20

#: Total attempts on malformed/empty output (1 initial + 2 retries), matching piece_detector.
_MAX_ATTEMPTS = 3


class TextShaperError(RuntimeError):
    """The Claude CLI text->voxel emit was unavailable or unusable.

    Subclasses :class:`RuntimeError` so the production route's existing
    ``RuntimeError -> 503`` handling catches it even if a caller forgets to handle
    it explicitly. The route catches it by name for a clear 503.
    """


def _build_prompt(description: str) -> str:
    """Build the sparse-occupancy prompt for a description."""
    hi = _GRID_N - 1
    return (
        f"You are a voxel sculptor. Output a 3D voxel model of: {description}.\n"
        f"Use a {_GRID_N}x{_GRID_N}x{_GRID_N} integer lattice. X and Z are the "
        f"horizontal footprint; Y is vertical (Y=0 is the ground -- the model must "
        f"rest on the ground). Coordinates are integers in [0, {hi}].\n"
        "Return ONLY valid JSON, no other text, in exactly this shape:\n"
        '{"voxels": [[x, y, z], ...]}\n'
        "where each [x, y, z] is one OCCUPIED cell. Make the object recognizable, "
        "solid (not a hollow shell), connected, and grounded. Use about 80-400 "
        "voxels -- enough to be recognizable, few enough to emit quickly."
    )


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences from Claude output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_voxels(raw_output: str) -> list[tuple[int, int, int]]:
    """Parse Claude output into a list of in-bounds ``(x, y, z)`` integer coords.

    Strips markdown fences, parses the strict ``{"voxels": [[x,y,z], ...]}``
    schema, and CLAMPS each coordinate into ``[0, _GRID_N-1]`` so a slightly
    out-of-range model coordinate is salvaged rather than discarded. Individual
    malformed entries (wrong length, non-integer) are skipped; the emit only fails
    if NOTHING usable remains.

    Raises:
        json.JSONDecodeError: output is not valid JSON.
        ValueError: JSON is not ``{"voxels": [list]}`` or yields no valid voxel.
    """
    cleaned = _strip_markdown_fences(raw_output)
    data = json.loads(cleaned)
    if not isinstance(data, dict) or "voxels" not in data:
        raise ValueError('expected a JSON object with a "voxels" key')
    raw_voxels = data["voxels"]
    if not isinstance(raw_voxels, list):
        raise ValueError('"voxels" must be a list')

    hi = _GRID_N - 1
    coords: list[tuple[int, int, int]] = []
    for item in raw_voxels:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            continue  # skip a malformed entry rather than failing the whole emit
        try:
            x, y, z = int(item[0]), int(item[1]), int(item[2])
        except (ValueError, TypeError):
            continue
        coords.append((min(hi, max(0, x)), min(hi, max(0, y)), min(hi, max(0, z))))

    if not coords:
        raise ValueError("no valid voxels in model output")
    return coords


def _fill_grid(coords: list[tuple[int, int, int]]) -> np.ndarray:
    """Fill a dense bool grid from sparse coords, crop to bbox, edge-pad sub-MIN axes.

    The model emits into a ``_GRID_N**3`` lattice; cropping to the occupied
    bounding box yields a tighter build and faster packing. Every axis is then
    ``<= _GRID_N`` (within the footprint/height caps), so only the lower bound
    needs enforcing -- an axis under ``MIN_GRID_DIM`` is edge-padded (repeating the
    boundary layer keeps a thin object connected rather than gluing on an empty slab).
    """
    grid = np.zeros((_GRID_N, _GRID_N, _GRID_N), dtype=bool)
    for x, y, z in coords:
        grid[x, y, z] = True

    occupied = np.argwhere(grid)
    lo = occupied.min(axis=0)
    hi = occupied.max(axis=0) + 1
    cropped = grid[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]

    pad_width = [(0, max(0, MIN_GRID_DIM - size)) for size in cropped.shape]
    if any(hi_pad for _, hi_pad in pad_width):
        cropped = np.pad(cropped, pad_width, mode="edge")

    return np.ascontiguousarray(cropped)


class TextShaper(Shaper):
    """``Shaper`` that turns a text description into an (X, Y, Z) voxel grid.

    Constructed by the ``/api/generate/from-text`` route with the user's
    description. No resolution arg: the model emits into a fixed ``_GRID_N**3``
    lattice.
    """

    def __init__(self, description: str) -> None:
        self._description = description

    def to_voxels(self) -> VoxelGrid:
        """Emit a sparse occupancy via Claude, fill+fit the grid, validate.

        Retries malformed/empty model output up to ``_MAX_ATTEMPTS``; a subprocess
        failure (no token, non-zero exit) is not retried. Exhausting retries or a
        subprocess failure raises :class:`TextShaperError` so the route returns 503.
        """
        prompt = _build_prompt(self._description)
        last_err: Exception | None = None

        for _ in range(_MAX_ATTEMPTS):
            try:
                raw = run_claude_text(prompt)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                # No token / non-zero exit / timeout: the CLI is unavailable or too
                # slow. Not retryable -> surface as a clean 503 at the route.
                raise TextShaperError(f"Claude CLI unavailable: {exc}") from exc
            try:
                coords = _parse_voxels(raw)
                grid = _fill_grid(coords)
                return validate_grid(grid)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                last_err = exc  # malformed output: retry

        raise TextShaperError(
            f"Claude CLI did not return a usable voxel model after "
            f"{_MAX_ATTEMPTS} attempts: {last_err}"
        )

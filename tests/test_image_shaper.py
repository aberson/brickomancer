"""Tests for ``services.image_shaper.ImageShaper`` (Phase 3, Step 5).

Strategy
--------
The GPU/model-bound step (``_generate_mesh``) is the mock boundary: every test
that wants a grid patches it to return a fixture ``trimesh`` mesh, so the real
deterministic tail (``_voxelize`` -> ``_fit_to_bounds`` -> ``validate_grid``)
runs without a GPU or the Hunyuan3D weights. The model-unavailable paths are
exercised directly (CUDA gate, empty/degenerate mesh) without needing the model
installed.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import trimesh

from brickomancer.models.brick import MAX_GRID_DIM, MAX_GRID_HEIGHT, MIN_GRID_DIM
from brickomancer.services.image_shaper import ImageShaper, ModelUnavailableError
from brickomancer.services.shaper import Shaper, validate_grid


def _box(extents: tuple[float, float, float]) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=extents)


# ---------------------------------------------------------------------------
# Type / contract identity
# ---------------------------------------------------------------------------


def test_imageshaper_is_a_shaper() -> None:
    """ImageShaper implements the Shaper seam (so it is swap-compatible)."""
    assert issubclass(ImageShaper, Shaper)
    assert isinstance(ImageShaper("x.jpg"), Shaper)


def test_max_dim_out_of_bounds_rejected() -> None:
    with pytest.raises(ValueError, match="max_dim"):
        ImageShaper("x.jpg", max_dim=MAX_GRID_DIM + 1)
    with pytest.raises(ValueError, match="max_dim"):
        ImageShaper("x.jpg", max_dim=MIN_GRID_DIM - 1)


# ---------------------------------------------------------------------------
# Happy path: real voxelize/fit on a fixture mesh
# ---------------------------------------------------------------------------


def test_to_voxels_returns_contract_valid_grid() -> None:
    """A fixture mesh voxelizes into a grid that passes the seam contract."""
    mesh = _box((5.0, 3.0, 2.0))
    with patch.object(ImageShaper, "_generate_mesh", return_value=mesh):
        grid = ImageShaper("x.jpg", max_dim=10).to_voxels()

    # validate_grid is the seam's enforcement point; calling it again must not raise.
    validate_grid(grid)
    assert grid.dtype == np.bool_
    assert grid.ndim == 3
    assert grid.any()
    x, y, z = grid.shape
    assert MIN_GRID_DIM <= x <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= z <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= y <= MAX_GRID_HEIGHT


def test_axis_ordering_preserved_y_up() -> None:
    """Mesh axes map straight through: longer extent -> more voxels on that axis.

    A box with strictly decreasing extents (X>Y>Z) must yield a grid whose axis
    sizes are also strictly decreasing, proving the (X, Y_up, Z) mapping is not
    transposed.
    """
    mesh = _box((6.0, 4.0, 1.5))
    with patch.object(ImageShaper, "_generate_mesh", return_value=mesh):
        grid = ImageShaper("x.jpg", max_dim=12).to_voxels()

    x, y, z = grid.shape
    assert x > y > z, f"axis ordering not preserved: {grid.shape}"
    # Longest extent maps to ~max_dim voxels (allow rounding slop).
    assert abs(x - 12) <= 2


def test_thin_axis_padded_up_to_min_dim() -> None:
    """A near-flat mesh (one extent ~0) is padded so the footprint reaches MIN_GRID_DIM."""
    mesh = _box((5.0, 5.0, 0.05))  # Z is essentially a plane
    with patch.object(ImageShaper, "_generate_mesh", return_value=mesh):
        grid = ImageShaper("x.jpg", max_dim=10).to_voxels()

    assert grid.shape[2] >= MIN_GRID_DIM


# ---------------------------------------------------------------------------
# _fit_to_bounds unit behavior
# ---------------------------------------------------------------------------


def test_fit_to_bounds_crops_empty_border() -> None:
    """Empty rows/planes around the occupied region are trimmed away."""
    matrix = np.zeros((10, 8, 6), dtype=bool)
    matrix[3:6, 2:5, 1:4] = True  # a 3x3x3 occupied block with empty borders
    fitted = ImageShaper._fit_to_bounds(matrix)
    assert fitted.shape == (3, 3, 3)
    assert fitted.all()


def test_fit_to_bounds_center_crops_oversized_footprint() -> None:
    """A footprint axis larger than MAX_GRID_DIM is center-cropped into bounds."""
    matrix = np.ones((MAX_GRID_DIM + 6, 4, 4), dtype=bool)
    fitted = ImageShaper._fit_to_bounds(matrix)
    assert fitted.shape[0] == MAX_GRID_DIM
    assert fitted.shape[1] == 4
    assert fitted.shape[2] == 4


def test_fit_to_bounds_empty_raises_model_unavailable() -> None:
    with pytest.raises(ModelUnavailableError, match="empty"):
        ImageShaper._fit_to_bounds(np.zeros((4, 4, 4), dtype=bool))


# ---------------------------------------------------------------------------
# Model-unavailable paths -> ModelUnavailableError (route turns these into 503)
# ---------------------------------------------------------------------------


def test_no_cuda_raises_model_unavailable() -> None:
    """The CUDA gate fires before any model load (the Phase-0 lesson)."""
    with patch("torch.cuda.is_available", return_value=False):
        with pytest.raises(ModelUnavailableError, match="CUDA"):
            ImageShaper("x.jpg")._generate_mesh()


def test_degenerate_mesh_raises_model_unavailable() -> None:
    """A zero-extent mesh cannot be voxelized -> ModelUnavailableError, not a crash."""
    # All vertices coincide -> extents == [0, 0, 0] -> the extent guard fires.
    degenerate = trimesh.Trimesh(
        vertices=[[0, 0, 0], [0, 0, 0], [0, 0, 0]], faces=[[0, 1, 2]]
    )
    with pytest.raises(ModelUnavailableError, match="degenerate"):
        ImageShaper("x.jpg")._voxelize(degenerate)


def test_model_unavailable_is_runtime_error() -> None:
    """Subclassing RuntimeError lets the route's RuntimeError handling catch it too."""
    assert issubclass(ModelUnavailableError, RuntimeError)


# ---------------------------------------------------------------------------
# Pipeline caching (perf fix — load the 7.64 GB model at most once per process)
# ---------------------------------------------------------------------------


def test_load_pipeline_caches_construction() -> None:
    """`_load_pipeline` constructs the pipeline at most once across calls (lru_cache)."""
    import brickomancer.services.image_shaper as ish

    sentinel = object()
    ish._load_pipeline.cache_clear()
    try:
        with patch.object(ish, "_construct_pipeline", return_value=sentinel) as mock_ctor:
            first = ish._load_pipeline()
            second = ish._load_pipeline()
        assert first is sentinel and second is sentinel
        assert mock_ctor.call_count == 1, "the 7.64 GB pipeline must load only once"
    finally:
        ish._load_pipeline.cache_clear()  # don't leak the sentinel to other tests


def test_failed_pipeline_load_is_not_cached() -> None:
    """A failed load (no GPU / weights) is retried, not poisoned into the cache."""
    import brickomancer.services.image_shaper as ish

    ish._load_pipeline.cache_clear()
    try:
        with patch.object(
            ish, "_construct_pipeline", side_effect=ModelUnavailableError("boom")
        ) as mock_ctor:
            for _ in range(2):
                with pytest.raises(ModelUnavailableError):
                    ish._load_pipeline()
        assert mock_ctor.call_count == 2, "lru_cache must not cache the failure"
    finally:
        ish._load_pipeline.cache_clear()

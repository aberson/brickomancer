"""Contract tests for the Shaper seam (Phase 1 Step 2).

The Shaper is the single swap seam between the shape front-ends (ImageShaper,
TextShaper -- Steps 5/6) and the shared, deterministic backend (packer, writer,
render). These tests pin the voxel-grid output contract so any future Shaper that
violates it fails here, and prove the seam's output is consumable end-to-end by
its real production consumer, ``brick_packer.pack``.
"""

import numpy as np
import pytest

from brickomancer.services import brick_packer
from brickomancer.services.shaper import (
    MAX_GRID_DIM,
    MAX_GRID_HEIGHT,
    MIN_GRID_DIM,
    Shaper,
    StubShaper,
    validate_grid,
)

# --- the interface itself ------------------------------------------------------


def test_shaper_is_abstract() -> None:
    """The Shaper interface cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Shaper()  # type: ignore[abstract]


def test_stub_shaper_is_a_shaper() -> None:
    """StubShaper satisfies the Shaper interface."""
    assert isinstance(StubShaper(), Shaper)


# --- the output grid contract --------------------------------------------------


def test_stub_returns_ndarray() -> None:
    """to_voxels() returns a numpy ndarray."""
    assert isinstance(StubShaper().to_voxels(), np.ndarray)


def test_grid_dtype_is_bool() -> None:
    """The grid is a bool array (True = occupied), per the contract."""
    assert StubShaper().to_voxels().dtype == np.bool_


def test_grid_is_3d_xyz() -> None:
    """The grid is 3-dimensional (X, Y, Z)."""
    assert StubShaper().to_voxels().ndim == 3


def test_grid_dims_within_bounds() -> None:
    """Footprint (X, Z) within [MIN, MAX_GRID_DIM]; height (Y) within [MIN, MAX_GRID_HEIGHT]."""
    x, y, z = StubShaper().to_voxels().shape
    assert MIN_GRID_DIM <= x <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= z <= MAX_GRID_DIM
    assert MIN_GRID_DIM <= y <= MAX_GRID_HEIGHT


def test_grid_has_occupied_voxels() -> None:
    """A valid grid has at least one occupied voxel (not empty)."""
    assert StubShaper().to_voxels().any()


def test_y_up_ground_layer_is_fullest() -> None:
    """Y is the vertical axis: the Y=0 ground layer is strictly the fullest.

    The asymmetric stepped-pyramid stub shrinks each higher layer, so the ground
    layer carries more occupied voxels than the top. A transposed-axis grid (Y
    swapped with X or Z) would NOT be bottom-heavy -- this pins the Y-up
    convention where a symmetric box (the old stub) could not.
    """
    grid = StubShaper().to_voxels()
    per_layer = [int(grid[:, y, :].sum()) for y in range(grid.shape[1])]
    assert per_layer[0] == max(per_layer), "ground layer (Y=0) is not the fullest"
    assert per_layer[0] > per_layer[-1], "shape is not bottom-heavy (Y-up violated)"


def test_stub_shape_is_configurable() -> None:
    """StubShaper honors its constructor dimensions in (X, Y, Z) order."""
    assert StubShaper(size_x=3, size_y=5, size_z=2).to_voxels().shape == (3, 5, 2)


# --- validate_grid: the seam's single contract-enforcement point ---------------


@pytest.mark.parametrize("dtype", [np.int64, np.uint8, np.float32])
def test_validate_grid_coerces_to_bool(dtype: type) -> None:
    """A non-bool array is coerced to bool (nonzero -> True)."""
    out = validate_grid(np.ones((4, 4, 4), dtype=dtype))
    assert out.dtype == np.bool_
    assert out.all()


def test_validate_grid_accepts_arraylike_list() -> None:
    """A nested Python list (ArrayLike) is coerced and validated."""
    grid = [[[1, 0], [0, 1]], [[1, 1], [0, 0]]]  # 2x2x2 ints
    out = validate_grid(grid)
    assert out.dtype == np.bool_
    assert out.shape == (2, 2, 2)


@pytest.mark.parametrize("shape", [(4,), (4, 4), (4, 4, 4, 4)])
def test_validate_grid_rejects_non_3d(shape: tuple[int, ...]) -> None:
    """A grid that is not 3-D (1-D, 2-D, 4-D) is rejected."""
    with pytest.raises(ValueError, match="3-D"):
        validate_grid(np.ones(shape, dtype=bool))


def test_validate_grid_rejects_empty() -> None:
    """An all-False grid (no occupied voxels) is rejected."""
    with pytest.raises(ValueError, match="empty"):
        validate_grid(np.zeros((4, 4, 4), dtype=bool))


@pytest.mark.parametrize(
    "shape", [(1, 4, 4), (MAX_GRID_DIM + 1, 4, 4), (4, 4, 1), (4, 4, MAX_GRID_DIM + 1)]
)
def test_validate_grid_rejects_footprint_out_of_bounds(shape: tuple[int, int, int]) -> None:
    """An X or Z footprint outside [MIN_GRID_DIM, MAX_GRID_DIM] is rejected."""
    with pytest.raises(ValueError, match="footprint"):
        validate_grid(np.ones(shape, dtype=bool))


@pytest.mark.parametrize("shape", [(4, 1, 4), (4, MAX_GRID_HEIGHT + 1, 4)])
def test_validate_grid_rejects_height_out_of_bounds(shape: tuple[int, int, int]) -> None:
    """A Y height outside [MIN_GRID_DIM, MAX_GRID_HEIGHT] is rejected."""
    with pytest.raises(ValueError, match="height"):
        validate_grid(np.ones(shape, dtype=bool))


@pytest.mark.parametrize(
    "shape",
    [
        (MIN_GRID_DIM, MIN_GRID_DIM, MIN_GRID_DIM),     # (2, 2, 2)  -- min everything
        (MAX_GRID_DIM, MIN_GRID_DIM, MAX_GRID_DIM),     # (32, 2, 32) -- max footprint
        (MIN_GRID_DIM, MAX_GRID_HEIGHT, MIN_GRID_DIM),  # (2, 64, 2)  -- max height (tall tower)
    ],
)
def test_validate_grid_accepts_boundary_dims(shape: tuple[int, int, int]) -> None:
    """The inclusive boundary dimensions are ACCEPTED (off-by-one guard)."""
    out = validate_grid(np.ones(shape, dtype=bool))
    assert out.shape == shape


# --- silent-wiring check: the seam output flows through the real consumer -------


def test_stub_grid_packs_through_production_consumer() -> None:
    """The Shaper output is consumable end-to-end by brick_packer.pack.

    The integration check required by the workspace silent-wiring rule: the seam
    is exercised through its real production consumer (the packer), not just
    asserted in isolation. The asymmetric grounded stub is a non-trivial shape;
    a contract drift the packer rejects fails here.
    """
    grid = StubShaper().to_voxels()
    placements = brick_packer.pack(grid, color_id=15)
    assert len(placements) > 0, "packer produced no bricks from a valid stub grid"
    for bp in placements:
        assert bp.color_id == 15
        assert bp.part_id

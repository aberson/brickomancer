"""The Shaper seam: the single interface every shape front-end implements.

A ``Shaper`` converts some input (an image, a text description) into a voxel
occupancy grid. Everything downstream of the grid -- the connectivity-graph
packer, the LDraw writer, color assignment, rendering -- is shared and untouched
by *which* Shaper produced the grid. This is the swap seam the rebuild is built
around: the hard, creative shape step is isolated behind ``to_voxels()``; the
mechanical packing/rendering stays shared and deterministic.

Voxel-grid contract (the output of every Shaper -- spelled out so a fresh model
can implement a Shaper without reverse-engineering the packer):

  - ``numpy.ndarray``, ``dtype=bool``, shape ``(X, Y, Z)``.
  - ``Y`` is the VERTICAL axis: ``Y=0`` is the ground layer, ``Y`` increases
    upward. ``(0, 0, 0)`` is the origin corner.
  - ``True`` = a brick occupies that voxel; ``False`` = empty.
  - ``X`` and ``Z`` are the horizontal FOOTPRINT: each must be in
    ``[MIN_GRID_DIM, MAX_GRID_DIM]`` (the packer pads a sub-2 footprint up to 2 and
    is masonry-constrained, so the footprint is capped for V1 shapes).
  - ``Y`` is the build HEIGHT in layers: ``[MIN_GRID_DIM, MAX_GRID_HEIGHT]``. The
    packer treats Y as unbounded layers, so height gets a separate, generous
    sanity cap rather than the footprint max -- a tall, thin tower is valid.
  - This is the SAME convention v1 used and the connectivity-graph packer
    consumes verbatim -- ``brick_packer.pack`` docstring: "numpy.ndarray[bool] of
    shape (X, Y, Z) where True = occupied". ``pack`` is the production consumer.

Construction pattern (how the concrete shapers in Steps 5/6 are wired):

  Each concrete Shaper holds its own INPUT and any CONFIG (e.g. voxel resolution)
  via its CONSTRUCTOR; ``to_voxels()`` stays uniform and no-arg. The constructors
  differ because the inputs differ -- that is expected, and the production routes
  construct the concrete shaper directly:

      # from-image route (Step 5):
      grid = ImageShaper(str(image_path), max_dim=resolution).to_voxels()
      colors = color_service.extract_colors(str(image_path))  # color is separate

      # from-text route (Step 6):
      grid = TextShaper(description).to_voxels()  # fixed 20**3, no resolution arg

  The seam is GEOMETRY-ONLY: color is extracted separately from the source image
  (or defaulted for text), never carried through ``to_voxels()``.

Until the concrete shapers land, ``StubShaper`` provides a valid reference grid so
the seam and its contract test exist and the downstream packer can be exercised
end-to-end.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import numpy.typing as npt

# Re-exported from the single-source-of-truth leaf (models/brick.py) so seam
# consumers can import them from the seam module. validate_grid uses all three.
from brickomancer.models.brick import MAX_GRID_DIM, MAX_GRID_HEIGHT, MIN_GRID_DIM

__all__ = [
    "MAX_GRID_DIM",
    "MAX_GRID_HEIGHT",
    "MIN_GRID_DIM",
    "Shaper",
    "StubShaper",
    "VoxelGrid",
    "validate_grid",
]

#: A voxel occupancy grid: bool ndarray of shape (X, Y, Z), Y-up, True = occupied.
VoxelGrid = npt.NDArray[np.bool_]


class Shaper(ABC):
    """Interface every shape front-end implements: input -> (X, Y, Z) bool grid.

    Concrete subclasses hold their own input (an image path, a text description)
    and any config (resolution) via their constructor and implement
    :meth:`to_voxels`. The *output* contract is fixed regardless of input -- see
    the module docstring for the full voxel-grid contract and construction
    pattern. This uniform seam is the only thing the rest of the pipeline
    (packer, writer, color, render) ever sees.
    """

    @abstractmethod
    def to_voxels(self) -> VoxelGrid:
        """Return the (X, Y, Z) bool occupancy grid for this shaper's input.

        Returns:
            ``np.ndarray``, ``dtype=bool``, shape ``(X, Y, Z)``, Y-up (``Y=0`` =
            ground layer), ``True`` = occupied. ``X``/``Z`` (footprint) in
            ``[MIN_GRID_DIM, MAX_GRID_DIM]``; ``Y`` (height) in
            ``[MIN_GRID_DIM, MAX_GRID_HEIGHT]``. Implementations should pass their
            result through :func:`validate_grid` so a malformed grid fails loudly
            at the seam rather than deep inside the packer.
        """
        ...


def validate_grid(grid: npt.ArrayLike) -> VoxelGrid:
    """Validate and normalize a voxel grid against the Shaper output contract.

    The single enforcement point for the seam's contract: every concrete Shaper
    should return ``validate_grid(...)`` so a contract violation surfaces at the
    seam boundary, not as a confusing failure deep in ``brick_packer.pack``.

    Args:
        grid: Anything array-like; coerced to a contiguous ``bool`` ndarray.

    Returns:
        The grid as a contiguous ``bool`` ndarray of shape ``(X, Y, Z)``.

    Raises:
        ValueError: if the grid is not 3-D, the X/Z footprint is outside
            ``[MIN_GRID_DIM, MAX_GRID_DIM]``, the Y height is outside
            ``[MIN_GRID_DIM, MAX_GRID_HEIGHT]``, or no voxel is occupied.
    """
    arr = np.ascontiguousarray(np.asarray(grid, dtype=bool))
    if arr.ndim != 3:
        raise ValueError(f"voxel grid must be 3-D (X, Y, Z), got shape {arr.shape}")
    size_x, size_y, size_z = arr.shape
    for axis, size in (("X", size_x), ("Z", size_z)):
        if not (MIN_GRID_DIM <= size <= MAX_GRID_DIM):
            raise ValueError(
                f"{axis} footprint {size} out of bounds [{MIN_GRID_DIM}, {MAX_GRID_DIM}]"
            )
    if not (MIN_GRID_DIM <= size_y <= MAX_GRID_HEIGHT):
        raise ValueError(
            f"Y height {size_y} out of bounds [{MIN_GRID_DIM}, {MAX_GRID_HEIGHT}]"
        )
    if not arr.any():
        raise ValueError("voxel grid is empty (no occupied voxels)")
    return arr


class StubShaper(Shaper):
    """Trivial reference Shaper: a grounded, asymmetric stepped pyramid.

    A placeholder so the seam and its contract test exist before the real
    ``ImageShaper`` (Step 5) and ``TextShaper`` (Step 6) land. The shape is
    deliberately ASYMMETRIC and bottom-heavy (each higher layer occupies a
    smaller corner-anchored footprint) so the contract test can actually pin the
    Y-up convention -- a symmetric box would pass a transposed-axis grid too.
    Returns a deterministic, grounded, fully-connected, packable, contract-valid
    grid. NOT wired into the API routes (those stay 503 until Steps 5-6); this
    exists purely to prove the seam.
    """

    def __init__(self, size_x: int = 4, size_y: int = 5, size_z: int = 3) -> None:
        self._shape = (size_x, size_y, size_z)

    def to_voxels(self) -> VoxelGrid:
        """Return a grounded stepped pyramid: layer ``y`` shrinks from the origin.

        Each layer's footprint is a subset of the layer below (anchored at the
        origin corner), so every occupied voxel sits directly on an occupied
        voxel below -- fully grounded and connected. The ground layer (``Y=0``)
        is the largest, giving a strictly bottom-heavy shape.
        """
        size_x, size_y, size_z = self._shape
        grid = np.zeros(self._shape, dtype=bool)
        for y in range(size_y):
            xe = max(1, size_x - y)
            ze = max(1, size_z - y)
            grid[:xe, y, :ze] = True
        return validate_grid(grid)

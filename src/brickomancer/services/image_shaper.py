"""Image ``Shaper``: a photo -> a true-3D voxel grid via Hunyuan3D-2mini.

Phase 3, Step 5. Replaces the v1 silhouette+dome heuristic (which fabricated depth)
with a real image->3D model. The pipeline, end to end:

    rembg background removal  ->  Hunyuan3D-2mini geometry  ->
    trimesh.voxelized(pitch, method="subdivide").fill()  ->  (X, Y, Z) bool grid

Everything downstream (the connectivity-graph packer, LDraw writer, render) is
shared and consumes whatever grid this emits -- see ``services/shaper.py`` for the
seam contract. This module is the swap point: it is the only place the heavy,
GPU-bound shape step lives.

Graceful degradation
--------------------
The model load is gated on a working CUDA GPU and a present Hunyuan3D install +
weights. Any of those being unavailable raises :class:`ModelUnavailableError`
(a ``RuntimeError`` subclass) so the production route can return a clean 503
instead of a 500. The Phase-0 spike (``docs/investigations/rebuild/
04-model-spike-result.md``) established the only non-obvious install gotcha: a
bare ``torch`` install silently lands the CPU wheel, so we gate on
``torch.cuda.is_available()`` before any model load.

Orientation note (operator-test tuning knob)
--------------------------------------------
The Hunyuan mesh arrives Y-up (glb convention), which this module preserves
verbatim: voxel-matrix axis 0 -> X, axis 1 -> Y (vertical), axis 2 -> Z. The
plan's live star-survival check (top-down silhouette has >= 4 protrusions) is a
separate operator Test; if a generated shape needs re-canonicalizing so its
features survive a top-down projection, that orientation tuning belongs here --
it is intentionally out of scope for the automated gate.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
import trimesh

from brickomancer.models.brick import MAX_GRID_DIM, MAX_GRID_HEIGHT, MIN_GRID_DIM
from brickomancer.services.shaper import Shaper, VoxelGrid, validate_grid

__all__ = ["ImageShaper", "ModelUnavailableError"]

#: Hugging Face repo + subfolder for the Phase-0-chosen image->3D model.
_MODEL_REPO = "tencent/Hunyuan3D-2mini"
_MODEL_SUBFOLDER = "hunyuan3d-dit-v2-mini"

#: Default voxel resolution: the mesh's longest extent maps to this many voxels.
#: 28 matches the Phase-0 spike (``pitch = extents.max() / 28``) where the star
#: voxelized recognizably without exceeding the footprint cap.
_DEFAULT_MAX_DIM = 28


class ModelUnavailableError(RuntimeError):
    """The Hunyuan3D model, its weights, or a working CUDA GPU is unavailable.

    Subclasses :class:`RuntimeError` so the production route's existing
    ``RuntimeError -> 503`` handling catches it even if a future caller forgets
    to handle it explicitly. The route catches it by name for a clear 503.
    """


def _construct_pipeline() -> Any:
    """Import Hunyuan3D and load the shape pipeline; map any failure to ModelUnavailable.

    The shape-only pipeline skips the C++/CUDA texture extensions, which is why it
    installs cleanly on Windows (Phase-0 finding). Weights download once from Hugging
    Face on first use, then live in the HF cache.
    """
    try:
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    except ImportError as exc:
        raise ModelUnavailableError(
            "Hunyuan3D (hy3dgen) is not installed. Install it into the "
            "project environment to enable the image build path."
        ) from exc

    try:
        return Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            _MODEL_REPO, subfolder=_MODEL_SUBFOLDER
        )
    except Exception as exc:  # weights missing / HF unreachable / load error
        raise ModelUnavailableError(
            f"Failed to load Hunyuan3D weights ({_MODEL_REPO}): {exc}"
        ) from exc


@lru_cache(maxsize=1)
def _load_pipeline() -> Any:
    """Return the Hunyuan3D pipeline, loading it AT MOST ONCE per process.

    The 7.64 GB model load dominates image wall-clock (~17 min/request when loaded
    every call — Step 8 smoke). Caching it as a process singleton means repeat requests
    and the Step 10 harness eval loop pay the load cost only once. ``lru_cache`` does NOT
    cache exceptions, so a failed load (no GPU / weights) is retried on the next call
    rather than poisoning the cache.
    """
    return _construct_pipeline()


class ImageShaper(Shaper):
    """``Shaper`` that turns an image file into an (X, Y, Z) voxel grid.

    Constructed by the ``/api/generate/from-image`` route with the saved upload
    path. Color is extracted separately (the seam is geometry-only), so this
    class only ever sees the image as model input.
    """

    def __init__(self, image_path: str, max_dim: int = _DEFAULT_MAX_DIM) -> None:
        """Hold the input image path and the target voxel resolution.

        Args:
            image_path: Path to the (already-saved) input image.
            max_dim: The mesh's longest extent maps to this many voxels. Must be
                in ``[MIN_GRID_DIM, MAX_GRID_DIM]`` so the resulting footprint
                cannot exceed the packer's contract before fitting.
        """
        if not (MIN_GRID_DIM <= max_dim <= MAX_GRID_DIM):
            raise ValueError(
                f"max_dim {max_dim} out of bounds [{MIN_GRID_DIM}, {MAX_GRID_DIM}]"
            )
        self._image_path = image_path
        self._max_dim = max_dim

    def to_voxels(self) -> VoxelGrid:
        """Run the full image->3D->voxels pipeline and return a contract-valid grid.

        Raises:
            ModelUnavailableError: if the GPU / Hunyuan3D install / weights are
                unavailable, so the route can surface a clean 503.
            ValueError: via :func:`validate_grid` if the produced grid violates
                the seam contract.
        """
        mesh = self._generate_mesh()
        grid = self._voxelize(mesh)
        return validate_grid(grid)

    # -- heavy GPU path (the mock boundary for the route integration test) ----

    def _generate_mesh(self) -> trimesh.Trimesh:
        """rembg the image, run Hunyuan3D, return a single ``trimesh.Trimesh``.

        This is the GPU/model-bound step; the route integration test patches it
        so the deterministic voxelize -> fit -> validate -> pack tail runs for
        real without a GPU.
        """
        try:
            import torch
        except ImportError as exc:  # torch not installed at all
            raise ModelUnavailableError(
                "PyTorch is not installed; cannot run the image->3D model."
            ) from exc

        if not torch.cuda.is_available():
            raise ModelUnavailableError(
                "No CUDA GPU available (torch.cuda.is_available() is False). "
                "The image->3D model requires a working CUDA GPU; a CPU-only "
                "torch wheel will not work."
            )

        pipeline = _load_pipeline()
        subject = self._remove_background()

        try:
            output = pipeline(image=subject)
        except Exception as exc:  # inference failure (OOM, bad input, etc.)
            raise ModelUnavailableError(
                f"Hunyuan3D inference failed: {exc}"
            ) from exc

        mesh = output[0] if isinstance(output, (list, tuple)) else output
        return self._as_trimesh(mesh)

    def _remove_background(self) -> Any:
        """Open the input image and strip its background via rembg (salvaged v1 step)."""
        from PIL import Image
        from rembg import remove

        with Image.open(self._image_path) as raw_img:
            return remove(raw_img.convert("RGBA"))

    # -- deterministic geometry tail (runs for real in the route test) --------

    def _voxelize(self, mesh: trimesh.Trimesh) -> np.ndarray:
        """Voxelize a mesh into a tight, in-bounds (X, Y, Z) bool occupancy grid."""
        mesh = self._as_trimesh(mesh)
        extent = float(np.max(mesh.extents))
        if not np.isfinite(extent) or extent <= 0.0:
            raise ModelUnavailableError(
                "Generated mesh is degenerate (zero/invalid extent); "
                "cannot voxelize."
            )

        pitch = extent / self._max_dim
        voxels = mesh.voxelized(pitch, method="subdivide").fill()
        matrix = np.ascontiguousarray(np.asarray(voxels.matrix, dtype=bool))
        return self._fit_to_bounds(matrix)

    @staticmethod
    def _fit_to_bounds(matrix: np.ndarray) -> np.ndarray:
        """Crop to the occupied region, then clamp/pad each axis into contract bounds.

        Axis convention (preserved from the mesh, Y-up): 0 -> X footprint,
        1 -> Y height, 2 -> Z footprint. After cropping to the occupied bounding
        box, any footprint axis over ``MAX_GRID_DIM`` (or height over
        ``MAX_GRID_HEIGHT``) is center-cropped, and any axis under
        ``MIN_GRID_DIM`` is edge-padded (repeating the boundary layer keeps a
        thin object connected rather than gluing on an empty slab).
        """
        if not matrix.any():
            raise ModelUnavailableError(
                "Voxelization produced an empty grid (no occupied voxels)."
            )

        # 1. Crop to the occupied bounding box on every axis.
        occupied = np.argwhere(matrix)
        lo = occupied.min(axis=0)
        hi = occupied.max(axis=0) + 1
        cropped = matrix[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]

        # 2. Clamp oversized axes (center-crop), then 3. pad undersized axes.
        maxima = (MAX_GRID_DIM, MAX_GRID_HEIGHT, MAX_GRID_DIM)
        for axis, axis_max in enumerate(maxima):
            size = cropped.shape[axis]
            if size > axis_max:
                start = (size - axis_max) // 2
                cropped = cropped.take(range(start, start + axis_max), axis=axis)

        pad_width = []
        for size in cropped.shape:
            short = max(0, MIN_GRID_DIM - size)
            pad_width.append((0, short))
        if any(hi_pad for _, hi_pad in pad_width):
            cropped = np.pad(cropped, pad_width, mode="edge")

        return np.ascontiguousarray(cropped)

    @staticmethod
    def _as_trimesh(mesh: Any) -> trimesh.Trimesh:
        """Coerce a pipeline/loader output into a single ``trimesh.Trimesh``.

        Hunyuan3D returns a ``Trimesh``, but a glb round-trip can yield a
        ``Scene``; concatenating its geometry gives one watertight-ish mesh to
        voxelize.
        """
        if isinstance(mesh, trimesh.Trimesh):
            return mesh
        if isinstance(mesh, trimesh.Scene):
            dumped = mesh.dump(concatenate=True)
            if isinstance(dumped, trimesh.Trimesh):
                return dumped
        raise ModelUnavailableError(
            f"Unexpected mesh type from the image->3D model: {type(mesh)!r}"
        )

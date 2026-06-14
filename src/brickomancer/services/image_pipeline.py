"""Image pipeline â€” rembg background removal, TripoSR mesh generation, voxelization.

TripoSR and torch are NOT listed in pyproject.toml (CUDA-specific install required
separately).  rembg requires onnxruntime (CPU or GPU variant).  Both imports are
guarded so this module loads cleanly on any system; run() raises ImportError with a
helpful message when either dependency is absent.
"""

import io
import logging
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional rembg import â€” guarded because rembg calls sys.exit(1) when
# onnxruntime is absent, which would crash the collection phase.
# ---------------------------------------------------------------------------
try:
    from rembg import remove as _rembg_remove  # type: ignore[import-untyped]

    _REMBG_AVAILABLE = True
except (ImportError, SystemExit):
    _rembg_remove = None  # type: ignore[assignment]
    _REMBG_AVAILABLE = False

# ---------------------------------------------------------------------------
# Optional TripoSR import â€” guarded so the module loads without CUDA deps.
# ---------------------------------------------------------------------------
try:
    from tsr.system import TSR as _TSR  # type: ignore[import-untyped]

    _TSR_AVAILABLE = True
except ImportError:
    _TSR = None  # type: ignore[assignment]
    _TSR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers â€” constants
# ---------------------------------------------------------------------------

# 1 LEGO stud = 8 LDU (LDraw Units) = 9.6 mm = 0.0096 m.
# The plan spec referenced "pitch=8.0" in LDraw units; mesh coordinates are in
# metres after TripoSR's export + the _scale_mesh normalisation, so the correct
# pitch value here is 0.0096 m, not 8.0.
_STUD_METERS: float = 0.0096

# Minimum XZ footprint in studs for silhouette sampling. At height_studs=5 a
# star downsampled to 5x5 pixels loses all five points to LANCZOS blur; 20
# studs gives enough pixels to preserve thin radiating arms.
_MIN_FOOTPRINT_STUDS: int = 20

# ---------------------------------------------------------------------------
# Internal helpers â€” functions
# ---------------------------------------------------------------------------


def _remove_background(image_path: str) -> Image.Image:
    """Remove image background via rembg, returning a PIL RGBA image.

    Raises ImportError if rembg / onnxruntime is not installed.
    """
    if not _REMBG_AVAILABLE or _rembg_remove is None:
        raise ImportError(
            "rembg is not available (onnxruntime backend missing).  Install with:\n"
            "  pip install rembg[cpu]   # CPU inference\n"
            "  pip install rembg[gpu]   # NVIDIA/CUDA GPU inference"
        )
    with open(image_path, "rb") as fh:
        input_bytes = fh.read()
    output_bytes: bytes = _rembg_remove(input_bytes)
    return Image.open(io.BytesIO(output_bytes)).convert("RGBA")


def _run_triposr(pil_image: Image.Image, output_dir: Path) -> Path:
    """Run TripoSR inference on *pil_image* and export the mesh to *output_dir*.

    Returns the path of the exported .obj file.

    Raises ImportError if TripoSR / torch is not installed.
    """
    if not _TSR_AVAILABLE or _TSR is None:
        raise ImportError(
            "TripoSR is not installed.  Install it with:\n"
            "  pip install torch torchvision torchaudio "
            "--index-url https://download.pytorch.org/whl/cu118\n"
            "  pip install git+https://github.com/VAST-AI-Research/TripoSR.git"
        )

    import torch  # type: ignore[import-untyped]

    try:
        model = _TSR.from_pretrained(
            "stabilityai/TripoSR",
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
    except Exception as e:
        raise RuntimeError(
            "TripoSR model download failed. Check your internet connection: " + str(e)
        ) from e
    model.renderer.set_chunk_size(8192)
    model.to("cuda")

    # TripoSR expects a preprocessed tensor; use its own utility.
    from tsr.utils import remove_background as _tsr_remove_bg  # type: ignore[import-untyped]

    image_tensor = _tsr_remove_bg(pil_image, force=False)

    # ImagePreprocessor does np.array(image) with no channel stripping, so RGBA
    # produces a 4-channel tensor that the tokenizer's 3-channel normalizer rejects.
    # Composite on white to give TripoSR an RGB image regardless of rembg output.
    if isinstance(image_tensor, Image.Image) and image_tensor.mode == "RGBA":
        rgb = Image.new("RGB", image_tensor.size, (255, 255, 255))
        rgb.paste(image_tensor, mask=image_tensor.split()[3])
        image_tensor = rgb

    with torch.no_grad():
        scene_codes = model([image_tensor], device="cuda")

    mesh = model.extract_mesh(scene_codes, resolution=64)[0]
    obj_path = output_dir / "mesh.obj"
    mesh.export(str(obj_path))
    return obj_path


def _scale_mesh(mesh: trimesh.Trimesh, height_studs: int) -> trimesh.Trimesh:
    """Scale *mesh* uniformly so its Y extent equals height_studs * _STUD_METERS.

    Assumes Y is the vertical axis (TripoSR default output orientation).
    If a mesh has Z-up orientation, rotate it to Y-up before calling this function.
    """
    y_extent = float(mesh.bounds[1][1] - mesh.bounds[0][1])
    if y_extent == 0:
        return mesh
    target_height = height_studs * _STUD_METERS
    scale_factor = target_height / y_extent
    mesh.apply_scale(scale_factor)
    return mesh


def _voxelize(mesh: trimesh.Trimesh, pitch: float = _STUD_METERS) -> np.ndarray:
    """Voxelize *mesh* and return a (X, Y, Z) bool numpy array.

    *pitch* is the voxel side length in the same unit as the mesh (metres after
    _scale_mesh).  The default _STUD_METERS (0.0096 m) makes each voxel row
    correspond to one stud.

    Uses method='subdivide' rather than method='ray' (the plan spec default) to
    avoid the optional 'rtree' package dependency; produces equivalent fill for
    watertight meshes.
    """
    voxels = mesh.voxelized(pitch=pitch, method="subdivide").fill()
    return np.asarray(voxels.matrix, dtype=bool)


def _extrude_silhouette(rgba_image: Image.Image, height_studs: int) -> np.ndarray:
    """Voxelise by extruding the rembg alpha-channel silhouette vertically.

    Produces a (X, height_studs, Z) bool array where every Y layer shares the
    same XZ cross-section matching the subject silhouette.  This gives far better
    shape fidelity for cartoon/clip-art images than TripoSR, which reconstructs
    them as roughly rectangular blobs.
    """
    if rgba_image.mode != "RGBA":
        rgba_image = rgba_image.convert("RGBA")
    w, h = rgba_image.size

    # Sample at high internal resolution so LANCZOS preserves thin star arms
    if w >= h:
        hires_x = max(height_studs, _MIN_FOOTPRINT_STUDS)
        hires_z = max(1, round(hires_x * h / w))
    else:
        hires_z = max(height_studs, _MIN_FOOTPRINT_STUDS)
        hires_x = max(1, round(hires_z * w / h))

    alpha = rgba_image.split()[3]
    alpha_bin = Image.fromarray((np.array(alpha) > 128).astype(np.uint8) * 255)
    alpha_hires = alpha_bin.resize((hires_x, hires_z), Image.Resampling.LANCZOS)
    mask_hires = np.array(alpha_hires) > 32  # shape (hires_z, hires_x)

    # Use the full hires mask directly as the output. Downsampling via OR-pool
    # fills the concave gaps between star arms (each ~2px wide at 20px resolution)
    # into a solid blob when the pool block spans ~3px. Keeping 1:1 resolution
    # preserves the five-arm silhouette and its concavities.
    output_x = hires_x
    output_z = hires_z

    mask_zx = np.zeros((output_z, output_x), dtype=bool)
    for ti in range(output_z):
        si0 = (ti * hires_z) // output_z
        si1 = max(si0 + 1, ((ti + 1) * hires_z) // output_z)
        for tj in range(output_x):
            sj0 = (tj * hires_x) // output_x
            sj1 = max(sj0 + 1, ((tj + 1) * hires_x) // output_x)
            mask_zx[ti, tj] = mask_hires[si0:si1, sj0:sj1].any()

    logger.info(
        "silhouette fill: %.1f%% (%d/%d studs)",
        mask_zx.mean() * 100,
        int(mask_zx.sum()),
        mask_zx.size,
    )
    if mask_zx.sum() < 4:
        logger.warning("sparse rembg output â€” using solid fill fallback")
        mask_zx[:] = True

    voxels = np.zeros((output_x, height_studs, output_z), dtype=bool)
    for y in range(height_studs):
        voxels[:, y, :] = mask_zx.T  # (output_z, output_x).T â†’ (output_x, output_z)
    return voxels


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(image_path: str, height_studs: int = 10) -> np.ndarray:
    """Full image pipeline: rembg background removal â†’ silhouette extrusion â†’ voxel grid.

    Uses 2-D alpha-channel extrusion so cartoon/clip-art images produce the correct
    silhouette shape instead of the rectangular blob that TripoSR reconstructs from
    flat cartoon inputs.

    Args:
        image_path: Path to the input image (JPEG, PNG, etc.).
        height_studs: Target height of the voxel grid in LEGO studs.

    Returns:
        numpy.ndarray[bool] of shape (X, height_studs, Z).

    Raises:
        ImportError: If rembg is not installed.
    """
    pil_image = _remove_background(image_path)
    alpha_arr = np.array(pil_image.split()[3])
    logger.info("rembg alpha fill: %.1f%%", alpha_arr.mean() / 255 * 100)
    return _extrude_silhouette(pil_image, height_studs)

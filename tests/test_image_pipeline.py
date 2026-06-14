"""Tests for image_pipeline — rembg background removal, silhouette extrusion, voxelization."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

import brickomancer.services.image_pipeline as ip

# ---------------------------------------------------------------------------
# Helpers — minimal valid OBJ mesh
# ---------------------------------------------------------------------------


def _write_cube_obj(path: Path, side: float = 1.0) -> None:
    """Write a minimal axis-aligned unit-cube OBJ to *path*."""
    h = side / 2.0
    lines = [
        "# minimal cube",
        f"v -{h} -{h} -{h}",
        f"v  {h} -{h} -{h}",
        f"v  {h}  {h} -{h}",
        f"v -{h}  {h} -{h}",
        f"v -{h} -{h}  {h}",
        f"v  {h} -{h}  {h}",
        f"v  {h}  {h}  {h}",
        f"v -{h}  {h}  {h}",
        # Six faces (CCW winding)
        "f 1 2 3 4",
        "f 5 8 7 6",
        "f 1 5 6 2",
        "f 2 6 7 3",
        "f 3 7 8 4",
        "f 4 8 5 1",
    ]
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cube_obj(tmp_path: Path) -> Path:
    """Return the path to a small cube OBJ file (side 0.1 m)."""
    p = tmp_path / "cube.obj"
    _write_cube_obj(p, side=0.1)
    return p


# ---------------------------------------------------------------------------
# Unit tests — _remove_background (rembg mocked — onnxruntime not available in CI)
# ---------------------------------------------------------------------------


def test_remove_background_returns_rgba_image(tmp_path: Path) -> None:
    """_remove_background returns a PIL RGBA image; rembg is mocked for CI."""
    import io

    from PIL import Image

    img = Image.new("RGB", (32, 32), color=(200, 100, 50))
    img_path = tmp_path / "test.jpg"
    img.save(img_path, format="JPEG")

    # Build a valid PNG bytes payload that rembg_remove would return.
    rgba_img = img.convert("RGBA")
    buf = io.BytesIO()
    rgba_img.save(buf, format="PNG")
    fake_rembg_output = buf.getvalue()

    def _fake_rembg_remove(data: bytes) -> bytes:
        return fake_rembg_output

    with patch.object(ip, "_rembg_remove", side_effect=_fake_rembg_remove):
        with patch.object(ip, "_REMBG_AVAILABLE", True):
            result = ip._remove_background(str(img_path))

    assert result.mode == "RGBA"
    assert result.size == (32, 32)


def test_remove_background_raises_when_rembg_unavailable(tmp_path: Path) -> None:
    """_remove_background raises ImportError with a helpful message when rembg is absent."""
    from PIL import Image

    img = Image.new("RGB", (32, 32), color=(200, 100, 50))
    img_path = tmp_path / "test.jpg"
    img.save(img_path, format="JPEG")

    with patch.object(ip, "_REMBG_AVAILABLE", False):
        with pytest.raises(ImportError, match="rembg is not available"):
            ip._remove_background(str(img_path))


# ---------------------------------------------------------------------------
# Unit tests — _scale_mesh
# ---------------------------------------------------------------------------


def test_scale_mesh_adjusts_y_extent(cube_obj: Path) -> None:
    """_scale_mesh scales the mesh so Y extent == height_studs * 0.0096."""
    mesh = trimesh.load(str(cube_obj), force="mesh")
    height_studs = 8
    scaled = ip._scale_mesh(mesh, height_studs)
    y_extent = float(scaled.bounds[1][1] - scaled.bounds[0][1])
    expected = height_studs * 0.0096
    assert abs(y_extent - expected) < 1e-6, f"Y extent {y_extent} != {expected}"


def test_scale_mesh_zero_y_extent_returns_unchanged() -> None:
    """_scale_mesh with a degenerate flat mesh does not raise."""
    flat = trimesh.creation.box(extents=[1.0, 0.0, 1.0])
    result = ip._scale_mesh(flat, 5)
    assert result is flat  # returned unchanged


# ---------------------------------------------------------------------------
# Unit tests — _voxelize
# ---------------------------------------------------------------------------


def test_voxelize_returns_bool_array(cube_obj: Path) -> None:
    """_voxelize returns a numpy bool array with 3 dimensions."""
    mesh = trimesh.load(str(cube_obj), force="mesh")
    scaled = ip._scale_mesh(mesh, 8)
    result = ip._voxelize(scaled, pitch=ip._STUD_METERS)
    assert isinstance(result, np.ndarray)
    assert result.dtype == bool
    assert result.ndim == 3


def test_voxelize_y_dimension_matches_height_studs(cube_obj: Path) -> None:
    """After scaling to height_studs, the Y voxel count is >= height_studs.

    trimesh voxelization places voxel centers at pitch/2 outside the mesh bounds,
    so the result is typically height_studs + 1 for a mesh scaled to exactly
    height_studs * _STUD_METERS.  The contract is Y >= height_studs.
    """
    height_studs = 8
    mesh = trimesh.load(str(cube_obj), force="mesh")
    scaled = ip._scale_mesh(mesh, height_studs)
    result = ip._voxelize(scaled, pitch=ip._STUD_METERS)
    # Y dimension must be at least height_studs (one row per stud)
    assert result.shape[1] >= height_studs, f"Expected Y>={height_studs}, got shape {result.shape}"


def test_voxelize_xz_dimensions_greater_than_two(cube_obj: Path) -> None:
    """X and Z dimensions are >= height_studs for a cube scaled to height_studs."""
    height_studs = 8
    mesh = trimesh.load(str(cube_obj), force="mesh")
    scaled = ip._scale_mesh(mesh, height_studs)
    result = ip._voxelize(scaled, pitch=ip._STUD_METERS)
    assert result.shape[0] >= height_studs, f"X={result.shape[0]} not >= {height_studs}"
    assert result.shape[2] >= height_studs, f"Z={result.shape[2]} not >= {height_studs}"


# ---------------------------------------------------------------------------
# Unit tests — _extrude_silhouette
# ---------------------------------------------------------------------------


def test_extrude_silhouette_height_dimension() -> None:
    """_extrude_silhouette Y dimension equals height_studs exactly."""
    from PIL import Image

    rgba = Image.new("RGBA", (20, 20), color=(255, 0, 0, 255))
    for height in (3, 5, 8, 10):
        result = ip._extrude_silhouette(rgba, height)
        assert result.shape[1] == height, f"Y={result.shape[1]} != {height}"


def test_extrude_silhouette_uniform_layers() -> None:
    """All Y layers share an identical XZ cross-section (pure vertical extrusion)."""
    from PIL import Image

    rgba = Image.new("RGBA", (20, 20), color=(0, 0, 0, 0))
    for x in range(10):
        for y in range(20):
            rgba.putpixel((x, y), (255, 0, 0, 255))

    result = ip._extrude_silhouette(rgba, height_studs=4)
    for y in range(1, 4):
        assert np.array_equal(result[:, y, :], result[:, 0, :])


def test_extrude_silhouette_rgb_input_treated_as_opaque() -> None:
    """RGB input (no alpha) is treated as fully opaque — all voxels filled."""
    from PIL import Image

    rgb = Image.new("RGB", (10, 10), color=(255, 0, 0))
    result = ip._extrude_silhouette(rgb, height_studs=4)
    assert result.all(), "All voxels should be filled for a fully opaque input"


# ---------------------------------------------------------------------------
# Unit tests — run()
# ---------------------------------------------------------------------------


def test_run_raises_import_error_when_rembg_unavailable(tmp_path: Path) -> None:
    """run() raises ImportError when rembg is absent."""
    from PIL import Image

    img = Image.new("RGB", (32, 32), color=(100, 150, 200))
    img_path = tmp_path / "input.jpg"
    img.save(img_path, format="JPEG")

    with patch.object(ip, "_REMBG_AVAILABLE", False):
        with pytest.raises(ImportError, match="rembg is not available"):
            ip.run(str(img_path), height_studs=8)


def test_run_returns_bool_array_shape(tmp_path: Path) -> None:
    """run() returns a (X, height_studs, Z) bool array; _remove_background is mocked."""
    from PIL import Image

    rgba = Image.new("RGBA", (32, 32), color=(200, 100, 50, 255))
    img_path = tmp_path / "input.jpg"
    rgba.convert("RGB").save(img_path, format="JPEG")

    with patch.object(ip, "_remove_background", return_value=rgba):
        result = ip.run(str(img_path), height_studs=8)

    assert isinstance(result, np.ndarray)
    assert result.dtype == bool
    assert result.ndim == 3
    assert result.shape[1] == 8, f"Expected Y==8, got shape {result.shape}"
    assert result.shape[0] > 0, f"X={result.shape[0]} must be > 0"
    assert result.shape[2] > 0, f"Z={result.shape[2]} must be > 0"


def test_run_default_height_studs_10(tmp_path: Path) -> None:
    """run() with default height_studs=10 returns shape (X, 10, Z)."""
    from PIL import Image

    rgba = Image.new("RGBA", (32, 32), color=(200, 200, 200, 255))
    img_path = tmp_path / "input.jpg"
    rgba.convert("RGB").save(img_path, format="JPEG")

    with patch.object(ip, "_remove_background", return_value=rgba):
        result = ip.run(str(img_path))  # default height_studs=10

    assert result.shape[1] == 10, f"Expected Y==10, got shape {result.shape}"

"""Integration tests for POST /api/generate/from-image (Phase 3, Step 5).

These exercise the production route end-to-end through ``TestClient`` -- the
code-quality requirement that a new component (``ImageShaper``) be reached from
its real caller, not just unit-tested in isolation. Only the GPU/model-bound
step is mocked:

  - ``ImageShaper._generate_mesh`` -> returns a fixture ``trimesh`` mesh, so the
    real voxelize -> fit -> pack tail runs.
  - ``suggestion_service.run_ldview`` -> touches the PNG (no LDView needed).

The uploaded bytes are a real PNG so ``color_service.extract_colors`` (which the
route calls on the same file) decodes it for real.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import trimesh
from fastapi.testclient import TestClient
from PIL import Image

from brickomancer.main import app
from brickomancer.services.image_shaper import ImageShaper, ModelUnavailableError


def _client() -> TestClient:
    return TestClient(app)


def _png_bytes() -> bytes:
    """A small two-color PNG so color extraction has something to cluster."""
    img = Image.new("RGB", (24, 24), (200, 30, 30))
    for x in range(12):
        for y in range(24):
            img.putpixel((x, y), (30, 30, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fixture_mesh() -> trimesh.Trimesh:
    """A small solid box -> a modest, fast-to-pack voxel grid."""
    return trimesh.creation.box(extents=(5.0, 4.0, 3.0))


def _touch_png(ldr_path: str, output_png: str) -> None:
    from pathlib import Path

    Path(output_png).touch()


def test_from_image_with_mocked_model_returns_packed_suggestions() -> None:
    """Happy path: model mocked, route reaches ImageShaper and returns 3 suggestions.

    Asserts a NON-503 packed response (the goal's clause c) and that the
    production caller actually invoked ImageShaper (``_generate_mesh`` called).
    """
    with (
        patch.object(
            ImageShaper, "_generate_mesh", autospec=True, return_value=_fixture_mesh()
        ) as mock_mesh,
        patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_touch_png,
        ),
    ):
        resp = _client().post(
            "/api/generate/from-image",
            data={"height_studs": "8"},
            files={"image": ("star.png", _png_bytes(), "image/png")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    suggestions = body["suggestions"]
    assert len(suggestions) == 3
    tiers = [s["tier"] for s in suggestions]
    assert tiers == ["compact", "standard", "detailed"]
    for s in suggestions:
        assert s["parts_count"] > 0
        assert len(s["parts_list"]) > 0
    # suggestion ids share one request uuid prefix and end _0/_1/_2
    prefix = suggestions[0]["id"].rsplit("_", 1)[0]
    assert [s["id"] for s in suggestions] == [f"{prefix}_{i}" for i in range(3)]
    # The production route actually reached ImageShaper (not a stub / shortcut).
    assert mock_mesh.called


def test_from_image_with_piece_images_still_reaches_shaper() -> None:
    """The multi-file (image + piece_images) form parses and reaches ImageShaper."""
    with (
        patch.object(
            ImageShaper, "_generate_mesh", autospec=True, return_value=_fixture_mesh()
        ),
        patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_touch_png,
        ),
        patch(
            "brickomancer.routers.generate.piece_detector.detect_pieces",
            return_value=[],
        ) as mock_detect,
    ):
        resp = _client().post(
            "/api/generate/from-image",
            data={"height_studs": "8"},
            files=[
                ("image", ("star.png", _png_bytes(), "image/png")),
                ("piece_images", ("piece1.png", _png_bytes(), "image/png")),
            ],
        )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["suggestions"]) == 3
    mock_detect.assert_called_once()


def test_from_image_model_unavailable_returns_503() -> None:
    """When the model/GPU/weights are unavailable, the route returns a clean 503.

    The goal's clause d: a well-formed request must surface 503 (not 500) so the
    rest of the local-first tool stays usable.
    """
    with patch.object(
        ImageShaper,
        "_generate_mesh",
        autospec=True,
        side_effect=ModelUnavailableError("no GPU"),
    ):
        resp = _client().post(
            "/api/generate/from-image",
            data={"height_studs": "8"},
            files={"image": ("star.png", _png_bytes(), "image/png")},
        )

    assert resp.status_code == 503, resp.text
    assert "no GPU" in resp.json()["detail"]


def test_from_image_missing_body_still_422() -> None:
    """A missing image body is still a validation 422, not a 503 or 500."""
    resp = _client().post("/api/generate/from-image")
    assert resp.status_code == 422

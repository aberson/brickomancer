"""Tests for main.py — /api/status endpoint and StaticFiles mount."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from brickomancer.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_status_returns_200_with_required_fields(client: TestClient) -> None:
    """GET /api/status returns 200 with status, llama_server_ok, ldview_ok, lpub3d_ok."""
    # Mock httpx to avoid real network call to llama-server
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("brickomancer.main.httpx.AsyncClient") as mock_client_cls:
        mock_async_client = AsyncMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_async_client

        response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "llama_server_ok" in body
    assert "ldview_ok" in body
    assert "lpub3d_ok" in body
    assert body["status"] == "ok"
    assert isinstance(body["llama_server_ok"], bool)
    assert isinstance(body["ldview_ok"], bool)
    assert isinstance(body["lpub3d_ok"], bool)


def test_status_llama_ok_false_when_server_unreachable(client: TestClient) -> None:
    """llama_server_ok is False when llama-server is unreachable."""
    import httpx as _httpx

    with patch("brickomancer.main.httpx.AsyncClient") as mock_client_cls:
        mock_async_client = AsyncMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)
        mock_async_client.get = AsyncMock(
            side_effect=_httpx.ConnectError("Connection refused")
        )
        mock_client_cls.return_value = mock_async_client

        response = client.get("/api/status")

    assert response.json()["llama_server_ok"] is False


def test_static_tmp_route_exists(client: TestClient) -> None:
    """The /static/tmp/ StaticFiles mount is registered and responds."""
    # The mount exists — requesting a non-existent file returns 404 (not 405 or connection error)
    # which confirms the StaticFiles mount is wired correctly.
    response = client.get("/static/tmp/nonexistent-file.png")
    # StaticFiles returns 404 for missing files, which is the correct behavior
    assert response.status_code == 404


def test_generate_from_image_missing_body_returns_422(client: TestClient) -> None:
    """POST /api/generate/from-image with no image file returns 422 (validation).

    The 503 stub keeps the required ``image`` parameter, so FastAPI still validates
    the body before the handler runs — a missing body is a 422, not a 503.
    """
    response = client.post("/api/generate/from-image")
    assert response.status_code == 422


def test_generate_from_image_stub_returns_503(client: TestClient) -> None:
    """POST /api/generate/from-image with a valid body returns the Phase-1 503 stub.

    The v1 image_pipeline was removed in Phase 1 Step 1; the ImageShaper lands in
    Step 5. Until then a well-formed request returns 503 (not a crash / 500).
    """
    response = client.post(
        "/api/generate/from-image",
        data={"height_studs": "8"},
        files={"image": ("cake.jpg", b"fake", "image/jpeg")},
    )
    assert response.status_code == 503
    assert "Shaper" in response.json()["detail"]


def test_generate_from_text_stub_returns_503(client: TestClient) -> None:
    """POST /api/generate/from-text with a valid body returns the Phase-1 503 stub.

    The v1 text_pipeline was removed in Phase 1 Step 1; the TextShaper lands in
    Step 6. Until then a well-formed request returns 503 (not a crash / 500).
    """
    response = client.post(
        "/api/generate/from-text",
        json={"description": "a blue birthday cake"},
    )
    assert response.status_code == 503
    assert "Shaper" in response.json()["detail"]


def test_generate_from_text_missing_description_returns_422(client: TestClient) -> None:
    """POST /api/generate/from-text with no description returns 422 (validation).

    Symmetric to the from-image missing-body check: the stub preserves the
    GenerateTextRequest schema, so a body missing the required ``description``
    is a 422 (validation), not the 503 stub.
    """
    response = client.post("/api/generate/from-text", json={})
    assert response.status_code == 422


def test_generate_from_image_stub_with_piece_images_returns_503(
    client: TestClient,
) -> None:
    """The stub preserves the multi-file signature: image + piece_images still 503s.

    Confirms the optional ``piece_images`` parameter is kept on the route so the
    documented multi-file form parses correctly and reaches the 503 stub (not a
    422 form-parse error).
    """
    response = client.post(
        "/api/generate/from-image",
        data={"height_studs": "8"},
        files=[
            ("image", ("cake.jpg", b"fake", "image/jpeg")),
            ("piece_images", ("piece1.jpg", b"fakepiece", "image/jpeg")),
        ],
    )
    assert response.status_code == 503
    assert "Shaper" in response.json()["detail"]


def test_generate_instructions_returns_404_for_missing_ldr(client: TestClient) -> None:
    """POST /api/generate/instructions returns 404 when LDR file does not exist."""
    import uuid

    suggestion_id = f"{uuid.uuid4()}_1"
    response = client.post(
        "/api/generate/instructions",
        json={"suggestion_id": suggestion_id},
    )
    assert response.status_code == 404


def test_generate_instructions_validates_uuid_prefix(client: TestClient) -> None:
    """POST /api/generate/instructions returns 422 for an invalid UUID prefix."""
    response = client.post(
        "/api/generate/instructions",
        json={"suggestion_id": "not-a-uuid_1"},
    )
    assert response.status_code == 422


def test_generate_instructions_validates_non_integer_tier(client: TestClient) -> None:
    """POST /api/generate/instructions returns 422 for a non-integer tier_index."""
    import uuid

    suggestion_id = f"{uuid.uuid4()}_notanint"
    response = client.post(
        "/api/generate/instructions",
        json={"suggestion_id": suggestion_id},
    )
    assert response.status_code == 422


def test_generate_instructions_validates_missing_underscore(
    client: TestClient,
) -> None:
    """POST /api/generate/instructions returns 422 when suggestion_id has no underscore."""
    response = client.post(
        "/api/generate/instructions",
        json={"suggestion_id": "badinput"},
    )
    assert response.status_code == 422


def test_colors_endpoint_returns_200(client: TestClient) -> None:
    """GET /api/colors returns 200 with a list (data layer wired)."""
    response = client.get("/api/colors")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_onnxruntime_gpu_not_installed() -> None:
    """onnxruntime-gpu must not be installed — it requires CUDA 12 but the project uses CUDA 11.8.

    The GPU package ships onnxruntime_providers_cuda.dll which depends on cublasLt64_12.dll.
    On a CUDA 11.8 system that DLL is absent, causing a loud error at every server startup.
    The project uses rembg[cpu] which pulls in onnxruntime (CPU) instead.
    """
    import importlib.metadata

    dist_map = importlib.metadata.packages_distributions()
    gpu_dists = dist_map.get("onnxruntime_gpu") or dist_map.get("onnxruntime-gpu")
    assert gpu_dists is None, (
        "onnxruntime-gpu is installed but must not be — it requires CUDA 12. "
        "Run `uv sync` to replace it with the CPU package via rembg[cpu]."
    )

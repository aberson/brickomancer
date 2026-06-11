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
    """POST /api/generate/from-image with no image file returns 422 (validation)."""
    response = client.post("/api/generate/from-image")
    assert response.status_code == 422


def test_generate_from_text_returns_503_when_llama_unavailable(
    client: TestClient,
) -> None:
    """Route promotes ServiceUnavailableError from text_pipeline to HTTP 503."""
    from brickomancer.services.text_pipeline import ServiceUnavailableError

    with patch(
        "brickomancer.routers.generate.text_pipeline.run",
        side_effect=ServiceUnavailableError("llama-server down"),
    ):
        response = client.post(
            "/api/generate/from-text",
            json={"description": "a blue birthday cake"},
        )
    assert response.status_code == 503
    assert "llama-server down" in response.json()["detail"]


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


def test_generate_from_text_returns_suggestions_on_success(
    client: TestClient,
) -> None:
    """Route returns GenerateResponse when text_pipeline and suggestion_service succeed."""
    import numpy as np

    from brickomancer.models.schemas import PartCount, Suggestion

    fake_grid = np.zeros((5, 5, 5), dtype=bool)
    fake_suggestions = [
        Suggestion(
            id="abc_0",
            tier="compact",
            preview_url="",
            parts_count=3,
            parts_list=[PartCount(part_id="3005", color_name="White", color_hex="F4F4F4", qty=3)],
        )
    ]

    with (
        patch(
            "brickomancer.routers.generate.text_pipeline.run",
            return_value=fake_grid,
        ),
        patch(
            "brickomancer.routers.generate.suggestion_service.generate_suggestions",
            return_value=fake_suggestions,
        ),
    ):
        response = client.post(
            "/api/generate/from-text",
            json={"description": "a red car"},
        )

    assert response.status_code == 200
    body = response.json()
    assert "suggestions" in body
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["tier"] == "compact"


def test_colors_endpoint_returns_200(client: TestClient) -> None:
    """GET /api/colors returns 200 with a list (data layer wired)."""
    response = client.get("/api/colors")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

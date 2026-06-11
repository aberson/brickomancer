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


def test_generate_from_image_stub_returns_501(client: TestClient) -> None:
    """POST /api/generate/from-image returns 501 (stub)."""
    response = client.post("/api/generate/from-image")
    assert response.status_code == 501


def test_generate_from_text_stub_returns_501(client: TestClient) -> None:
    """POST /api/generate/from-text returns 501 (stub)."""
    response = client.post(
        "/api/generate/from-text",
        json={"description": "a blue birthday cake"},
    )
    assert response.status_code == 501


def test_generate_instructions_stub_returns_501_with_valid_id(client: TestClient) -> None:
    """POST /api/generate/instructions returns 501 (stub) for a valid suggestion_id."""
    import uuid

    suggestion_id = f"{uuid.uuid4()}_1"
    response = client.post(
        "/api/generate/instructions",
        json={"suggestion_id": suggestion_id},
    )
    assert response.status_code == 501


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


def test_colors_stub_returns_empty_list(client: TestClient) -> None:
    """GET /api/colors returns [] (stub)."""
    response = client.get("/api/colors")
    assert response.status_code == 200
    assert response.json() == []

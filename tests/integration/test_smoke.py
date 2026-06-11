"""Smoke integration tests — exercise the full pipeline against a live server.

These tests require real services to be running:
- llama-server on port 8080 (for from-text route)
- TripoSR installed (for from-image route)

Run with:  uv run pytest tests/integration/ -m integration -v
Skip by default via ``-m "not integration"`` or by omitting the integration directory.

Both test functions are individually guarded with pytest.mark.skipif so that a
missing service causes a skip rather than a failure.
"""

import importlib.util
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Service availability checks
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "http://localhost:8000"

# Wall-clock timeout per request (read-inactivity); image pipeline can take ~2 min.
_TIMEOUT_S = 120


def _llama_server_available() -> bool:
    """Return True if llama-server is accepting connections on localhost:8080."""
    try:
        with socket.create_connection(("localhost", 8080), timeout=2):
            return True
    except OSError:
        return False


def _triposr_available() -> bool:
    """Return True if TripoSR (tsr package) is importable."""
    return importlib.util.find_spec("tsr") is not None


def _live_server_available() -> bool:
    """Return True if the FastAPI backend is running on localhost:8000."""
    try:
        resp = httpx.get(f"{BASE_URL}/api/status", timeout=3)
        return resp.status_code == 200
    except httpx.ConnectError:
        return False


# ---------------------------------------------------------------------------
# Module-level integration marker
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: assert standard GenerateResponse shape
# ---------------------------------------------------------------------------


def _assert_generate_response(body: dict[str, Any], expected_suggestion_count: int = 3) -> None:
    """Assert the GenerateResponse body has the expected structure."""
    assert "suggestions" in body, "Response missing 'suggestions' key"
    suggestions = body["suggestions"]
    assert isinstance(suggestions, list), "'suggestions' must be a list"
    assert len(suggestions) == expected_suggestion_count, (
        f"Expected {expected_suggestion_count} suggestions, got {len(suggestions)}"
    )
    tiers = ["compact", "standard", "detailed"]
    for i, suggestion in enumerate(suggestions):
        assert "id" in suggestion, f"suggestions[{i}] missing 'id'"
        assert "tier" in suggestion, f"suggestions[{i}] missing 'tier'"
        assert "preview_url" in suggestion, f"suggestions[{i}] missing 'preview_url'"
        assert "parts_count" in suggestion, f"suggestions[{i}] missing 'parts_count'"
        assert "parts_list" in suggestion, f"suggestions[{i}] missing 'parts_list'"
        assert isinstance(suggestion["parts_list"], list), (
            f"suggestions[{i}]['parts_list'] must be a list"
        )
        assert suggestion["tier"] == tiers[i], (
            f"suggestions[{i}]['tier'] expected '{tiers[i]}', got '{suggestion['tier']}'"
        )
        # preview_url may be empty string if LDView is not on PATH, but must be present
        assert isinstance(suggestion["preview_url"], str), (
            f"suggestions[{i}]['preview_url'] must be a string"
        )
        # compact tier may have an empty parts_list — that is acceptable
        # standard and detailed should normally have parts, but we only assert list type


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _live_server_available() or not _llama_server_available(),
    reason="Live server or llama-server not available on localhost:8080",
)
def test_from_text_returns_three_suggestions() -> None:
    """POST /api/generate/from-text returns 3 suggestions with required fields."""
    payload = {"description": "big blue birthday cake", "height_studs": 10}
    resp = httpx.post(
        f"{BASE_URL}/api/generate/from-text",
        json=payload,
        timeout=_TIMEOUT_S,
    )
    assert resp.status_code == 200, (
        f"Expected HTTP 200, got {resp.status_code}: {resp.text[:200]}"
    )
    _assert_generate_response(resp.json(), expected_suggestion_count=3)


@pytest.mark.skipif(
    not _live_server_available() or not _triposr_available(),
    reason="Live server or TripoSR not available",
)
def test_from_image_returns_three_suggestions() -> None:
    """POST /api/generate/from-image returns 3 suggestions with required fields."""
    cake_path = FIXTURES_DIR / "cake.jpg"
    assert cake_path.exists(), f"Fixture file missing: {cake_path}"

    with cake_path.open("rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/api/generate/from-image",
            files={"image": ("cake.jpg", f, "image/jpeg")},
            data={"height_studs": "10"},
            timeout=_TIMEOUT_S,
        )

    assert resp.status_code == 200, (
        f"Expected HTTP 200, got {resp.status_code}: {resp.text[:200]}"
    )
    _assert_generate_response(resp.json(), expected_suggestion_count=3)


@pytest.mark.skipif(
    not _live_server_available() or not _triposr_available(),
    reason="Live server or TripoSR not available",
)
def test_from_image_lego_cake_fixture() -> None:
    """POST /api/generate/from-image with lego_cake.jpeg fixture returns valid response."""
    lego_cake_path = FIXTURES_DIR / "lego_cake.jpeg"
    assert lego_cake_path.exists(), f"Fixture file missing: {lego_cake_path}"

    with lego_cake_path.open("rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/api/generate/from-image",
            files={"image": ("lego_cake.jpeg", f, "image/jpeg")},
            data={"height_studs": "10"},
            timeout=_TIMEOUT_S,
        )

    assert resp.status_code == 200, (
        f"Expected HTTP 200, got {resp.status_code}: {resp.text[:200]}"
    )
    _assert_generate_response(resp.json(), expected_suggestion_count=3)

"""Integration tests for POST /api/generate/from-text (Phase 3, Step 6).

These exercise the production route end-to-end through ``TestClient`` -- the
code-quality requirement that a new component (``TextShaper``) be reached from its
real caller, not just unit-tested. Only the external boundaries are mocked:

  - ``text_shaper.run_claude_text`` -> returns a canned sparse-voxel JSON, so the
    real parse -> fill -> validate -> pack tail runs.
  - ``suggestion_service.run_ldview`` -> touches the PNG (no LDView needed).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from brickomancer.main import app


def _client() -> TestClient:
    return TestClient(app)


def _solid_block_json(n: int = 6) -> str:
    coords = [[x, y, z] for x in range(n) for y in range(n) for z in range(n)]
    return json.dumps({"voxels": coords})


def _touch_png(ldr_path: str, output_png: str) -> None:
    Path(output_png).touch()


def test_from_text_with_mocked_cli_returns_packed_suggestions() -> None:
    """Happy path: subprocess mocked, route reaches TextShaper and returns 3 suggestions."""
    with (
        patch(
            "brickomancer.services.text_shaper.run_claude_text",
            return_value=_solid_block_json(6),
        ) as mock_cli,
        patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_touch_png,
        ),
    ):
        resp = _client().post(
            "/api/generate/from-text",
            json={"description": "a five-pointed star"},
        )

    assert resp.status_code == 200, resp.text
    suggestions = resp.json()["suggestions"]
    assert len(suggestions) == 3
    assert [s["tier"] for s in suggestions] == ["compact", "standard", "detailed"]
    for s in suggestions:
        assert s["parts_count"] > 0
        assert len(s["parts_list"]) > 0
    prefix = suggestions[0]["id"].rsplit("_", 1)[0]
    assert [s["id"] for s in suggestions] == [f"{prefix}_{i}" for i in range(3)]
    # The production route actually reached TextShaper (not a stub / shortcut).
    assert mock_cli.called


def test_from_text_unusable_model_output_returns_503() -> None:
    """When the Claude CLI never returns a usable model, the route returns a clean 503."""
    with patch(
        "brickomancer.services.text_shaper.run_claude_text",
        return_value="not json at all",
    ):
        resp = _client().post(
            "/api/generate/from-text",
            json={"description": "a five-pointed star"},
        )

    assert resp.status_code == 503, resp.text
    assert "voxel model" in resp.json()["detail"]


def test_from_text_cli_unavailable_returns_503() -> None:
    """A subprocess failure (e.g. no OAUTH token) surfaces as a clean 503, not a 500."""
    with patch(
        "brickomancer.services.text_shaper.run_claude_text",
        side_effect=RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set"),
    ):
        resp = _client().post(
            "/api/generate/from-text",
            json={"description": "a star"},
        )

    assert resp.status_code == 503, resp.text
    assert "Claude CLI unavailable" in resp.json()["detail"]


def test_from_text_missing_description_still_422() -> None:
    """A missing description is still a validation 422, reached before TextShaper."""
    resp = _client().post("/api/generate/from-text", json={})
    assert resp.status_code == 422

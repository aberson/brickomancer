"""End-to-end smoke tests against the REAL rebuilt services (Phase 3, Step 8).

Unlike the unit/route tests (which mock the model / subprocess / render), these
exercise the full pipeline with NOTHING mocked:

  - image path: rembg -> Hunyuan3D-2mini -> voxelize -> pack -> LDraw -> LDView preview
  - text path:  ``claude -p`` sparse-voxel emit -> pack -> LDraw -> LDView preview
  - instructions: LPub3D renders a multi-page PDF (BOM page) from a generated .ldr

These are the pytest-vs-render blind spot the rebuild exists to close. They are
gated on ``BRICKOMANCER_INTEGRATION=1`` (the workspace integration gate) AND on
per-path service availability, so a missing service SKIPS rather than fails.

Run (PowerShell, with the model + tools + token available):

    # load CLAUDE_CODE_OAUTH_TOKEN from the Windows user env (it is not in .env):
    $env:CLAUDE_CODE_OAUTH_TOKEN = `
        [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")
    $env:PATH += ";C:\\Tools\\LPub3D"
    $env:BRICKOMANCER_INTEGRATION = "1"
    uv run pytest tests/integration/ -v -s

SLOW (real model inference): image ~100 s+, text ~165 s. ``-s`` shows the recorded
per-call wall-clock.
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from brickomancer.main import app

_FIXTURES = Path(__file__).parent / "fixtures"
_CAKE = _FIXTURES / "cake.jpg"

# Workspace integration gate: skip the whole module unless explicitly enabled.
pytestmark = pytest.mark.skipif(
    os.environ.get("BRICKOMANCER_INTEGRATION") != "1",
    reason="integration gate off — set BRICKOMANCER_INTEGRATION=1 to run",
)


def _image_model_available() -> bool:
    """True if Hunyuan3D (hy3dgen) is importable AND a CUDA GPU is present."""
    if importlib.util.find_spec("hy3dgen") is None:
        return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _claude_available() -> bool:
    return bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def _assert_three_suggestions(body: dict[str, Any]) -> None:
    suggestions = body["suggestions"]
    assert len(suggestions) == 3
    assert [s["tier"] for s in suggestions] == ["compact", "standard", "detailed"]
    for s in suggestions:
        assert s["parts_count"] > 0
        assert s["parts_list"], "each suggestion must have a parts list"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def text_generation(client: TestClient) -> dict[str, Any]:
    """One real text generation, shared by the text + instructions tests (saves a slow run)."""
    if not _claude_available():
        pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set")
    t = time.time()
    resp = client.post(
        "/api/generate/from-text",
        json={"description": "a small house", "height_studs": 8},
    )
    print(f"\n[smoke] from-text real (claude -p): {resp.status_code} in {time.time() - t:.0f}s")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_from_text_real(text_generation: dict[str, Any]) -> None:
    """Real Claude CLI text->voxel emit -> 3 packed, LDView-rendered suggestions."""
    _assert_three_suggestions(text_generation)


@pytest.mark.skipif(not _image_model_available(), reason="hy3dgen/CUDA unavailable")
def test_from_image_real(client: TestClient) -> None:
    """Real rembg -> Hunyuan3D-2mini -> voxelize -> 3 packed, LDView-rendered suggestions."""
    assert _CAKE.is_file(), f"missing fixture {_CAKE}"
    t = time.time()
    with _CAKE.open("rb") as fh:
        resp = client.post(
            "/api/generate/from-image",
            data={"height_studs": "8"},
            files={"image": ("cake.jpg", fh, "image/jpeg")},
        )
    print(f"\n[smoke] from-image real (Hunyuan3D): {resp.status_code} in {time.time() - t:.0f}s")
    assert resp.status_code == 200, resp.text
    _assert_three_suggestions(resp.json())


def test_instructions_pdf_real(client: TestClient, text_generation: dict[str, Any]) -> None:
    """Full pipeline + LPub3D: render a multi-page instruction PDF from a generated build.

    Render-verifies the frozen BOM-only header through the production route (the
    COVER_PAGE-crash path from Step 7) end-to-end, not via a standalone script.
    """
    suggestion_id = text_generation["suggestions"][1]["id"]  # standard tier
    t = time.time()
    resp = client.post("/api/generate/instructions", json={"suggestion_id": suggestion_id})
    print(f"\n[smoke] instructions PDF real (LPub3D): {resp.status_code} in {time.time() - t:.0f}s")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 1000, "PDF suspiciously small — possible LPub3D crash"

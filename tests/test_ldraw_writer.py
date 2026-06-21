"""Tests for ``ldraw_writer.write_ldr`` — the FROZEN BOM-only LPub3D header (Step 7).

Phase 0.2 froze the meta header to BOM-only because ``0 !LPUB INSERT COVER_PAGE``
CRASHES LPub3D 2.4.9 (render-verified) and FADE_STEPS churn drove the v1 plateau.
``tests/test_meta_header_fixture.py`` guards the frozen FIXTURE; these tests guard
the PRODUCTION writer's output — the producer that was still emitting COVER_PAGE
until Step 7 closed the producer-consumer drift.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from brickomancer.services import brick_packer
from brickomancer.services.ldraw_writer import _BOM_META, write_ldr


def _ldr_text(tmp_path: Path) -> str:
    grid = np.ones((3, 2, 3), dtype=bool)  # small solid block -> multiple bricks/steps
    placements = brick_packer.pack(grid, color_id=15)
    assert placements, "packer should produce placements for a solid block"
    out = tmp_path / "suggestion_0.ldr"
    write_ldr(placements, str(out), tier_name="standard")
    return out.read_text(encoding="utf-8")


def _nonblank(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def test_frozen_bom_constant_present(tmp_path: Path) -> None:
    """The frozen BOM meta constant appears exactly once in the written file."""
    text = _ldr_text(tmp_path)
    assert _BOM_META == "0 !LPUB INSERT BOM"
    assert text.count(_BOM_META) == 1


def test_no_cover_page(tmp_path: Path) -> None:
    """COVER_PAGE must never appear — it crashes LPub3D 2.4.9 (Step 0.2)."""
    assert "COVER_PAGE" not in _ldr_text(tmp_path)


def test_header_is_bom_only(tmp_path: Path) -> None:
    """The ONLY `0 !` meta command emitted is the BOM (no FADE_STEPS, no COVER_PAGE)."""
    meta_lines = [ln for ln in _nonblank(_ldr_text(tmp_path)) if ln.startswith("0 !")]
    assert meta_lines, "writer must emit at least the BOM meta"
    for ln in meta_lines:
        assert "INSERT BOM" in ln, f"unexpected meta command from writer: {ln!r}"


def test_bom_after_last_step(tmp_path: Path) -> None:
    """BOM placement invariant: it comes after the final `0 STEP` (render-verified)."""
    lines = _nonblank(_ldr_text(tmp_path))
    bom_idx = next(i for i, ln in enumerate(lines) if "INSERT BOM" in ln)
    last_step_idx = max(i for i, ln in enumerate(lines) if ln == "0 STEP")
    assert bom_idx > last_step_idx


def test_has_brick_and_step_lines(tmp_path: Path) -> None:
    """A real build emits part lines and at least one step marker."""
    lines = _nonblank(_ldr_text(tmp_path))
    assert any(ln.startswith("1 ") for ln in lines)
    assert any(ln == "0 STEP" for ln in lines)

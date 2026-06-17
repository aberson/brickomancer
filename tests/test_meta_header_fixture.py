"""Tests for the frozen LPub3D meta-header fixtures (Phase 0 Step 0.2-prep).

These fixtures pin a known-good LPub3D meta header so the rebuild's instruction
toolchain (Step 7/9) renders a multi-page PDF with a BOM from a constant, never a
dynamically-generated header.  The frozen header is the artifact the harness is
forbidden to edit -- the v1 plateau postmortem traced ~30 commits of meta-command
oscillation (FADE_STEPS / HIGHLIGHT_STEP / COVER_PAGE / BOM churn) to a freely-
editable meta layer.

VERIFIED IN STEP 0.2 (render evidence, not assumption): on LPub3D 2.4.9 (this
project's pinned toolchain), `0 !LPUB INSERT COVER_PAGE` CRASHES the renderer
(writes LPub3D.dmp, no PDF).  The bare body -- `0 STEP`-delimited brick steps
followed by `0 !LPUB INSERT BOM` after the final step -- renders a clean
multi-page PDF (181 KB, parts pages + BOM).  This matches the structure of the
v1 LDR files that actually rendered in the harness (they never used COVER_PAGE).
So the frozen header is BOM + step-numbering ONLY, and the guard below explicitly
forbids COVER_PAGE.  See docs/investigations/rebuild/04-model-spike-result.md.
"""

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"
_META_HEADER = _FIXTURES / "lpub3d_meta_header.ldr"
_SMOKE = _FIXTURES / "toolchain_smoke.ldr"


def _nonblank_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_fixtures_exist_and_nonempty() -> None:
    """Both fixture files are present on disk and non-empty."""
    for path in (_META_HEADER, _SMOKE):
        assert path.is_file(), f"missing fixture: {path}"
        assert path.stat().st_size > 0, f"empty fixture: {path}"


def test_meta_header_contains_bom_and_steps() -> None:
    """Header has exactly one BOM and at least one step marker (the verified header)."""
    text = _META_HEADER.read_text(encoding="utf-8")
    assert text.count("0 !LPUB INSERT BOM") == 1
    assert text.count("0 STEP") >= 1


@pytest.mark.parametrize("path", [_META_HEADER, _SMOKE])
def test_no_cover_page_meta(path: Path) -> None:
    """Frozen-config guard (render-verified): COVER_PAGE must NEVER appear.

    On LPub3D 2.4.9 `0 !LPUB INSERT COVER_PAGE` crashes the renderer (Step 0.2
    reproduced this three times: a bare COVER_PAGE first produced a 1-page
    zero-size PDF, then crashed with an LPub3D.dmp).  Removing it renders a clean
    multi-page PDF.  This guard fails loudly if anyone reintroduces the meta the
    toolchain cannot handle -- the exact pytest-vs-render blind spot the rebuild
    closes.
    """
    text = path.read_text(encoding="utf-8")
    assert "COVER_PAGE" not in text, (
        f"{path.name} contains COVER_PAGE, which crashes LPub3D 2.4.9 (Step 0.2)"
    )


def test_meta_header_has_nothing_but_bom() -> None:
    """Frozen-config guard: the ONLY meta command in the header is BOM.

    The whitelist filters on the ``0 !`` prefix (ALL LDraw meta commands), not
    just ``0 !LPUB`` -- meta-churn can arrive as ``0 !FADE``, ``0 !SILHOUETTE``,
    ``0 !LEOCAD GROUP``, etc.  Any ``0 !`` line that is not BOM fails here, which
    is the regression this fixture exists to catch (v1 plateau: ~30 commits of
    FADE_STEPS / HIGHLIGHT_STEP / COVER_PAGE / BOM oscillation).
    """
    meta_lines = [ln for ln in _nonblank_lines(_META_HEADER) if ln.startswith("0 !")]
    assert meta_lines, "frozen header must contain at least the BOM meta"
    for ln in meta_lines:
        assert "INSERT BOM" in ln, (
            f"unexpected meta command in frozen header: {ln!r}"
        )


@pytest.mark.parametrize("path", [_META_HEADER, _SMOKE])
def test_every_line_is_valid_ldraw_type(path: Path) -> None:
    """Every non-blank line begins with a valid LDraw line type (0 meta or 1 part)."""
    for ln in _nonblank_lines(path):
        line_type = ln.split(maxsplit=1)[0]
        assert line_type in {"0", "1"}, f"invalid LDraw line type in {path.name}: {ln!r}"


def test_brick_lines_have_15_tokens() -> None:
    """Every `1 ` part line: 1 + color + 12 transform/position + part = 15 tokens.

    Only ``_SMOKE`` is checked -- ``_META_HEADER`` is a pure-meta template with no
    brick lines, so parametrizing it here would pass vacuously.
    """
    for ln in _nonblank_lines(_SMOKE):
        if ln.startswith("1 "):
            tokens = ln.split()
            assert len(tokens) == 15, f"malformed brick line: {ln!r}"
            assert tokens[-1].endswith(".dat"), f"part ref must end .dat: {ln!r}"


def test_smoke_has_bricks_and_steps() -> None:
    """The smoke body is a renderable model: >=2 brick lines and >=1 step marker."""
    lines = _nonblank_lines(_SMOKE)
    brick_lines = [ln for ln in lines if ln.startswith("1 ")]
    step_lines = [ln for ln in lines if ln == "0 STEP"]
    assert len(brick_lines) >= 2
    assert len(step_lines) >= 1


@pytest.mark.parametrize("path", [_META_HEADER, _SMOKE])
def test_bom_after_last_step(path: Path) -> None:
    """BOM placement invariant: it must come after the final `0 STEP` (render-verified)."""
    lines = _nonblank_lines(path)
    bom_idx = next(i for i, ln in enumerate(lines) if "INSERT BOM" in ln)
    last_step_idx = max(i for i, ln in enumerate(lines) if ln == "0 STEP")
    assert bom_idx > last_step_idx, f"BOM not after the last 0 STEP in {path.name}"

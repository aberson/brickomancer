"""Judge: dimension map, frozen constraints, and the change-brief prompt (Step 9).

Ported from the v1 judge (docs/rebuild_reference/judge.py) with the defining Step 9
change: the v1 judge handed the applier an ``LPUB3D_META_REFERENCE`` that *offered*
COVER_PAGE / FADE_STEPS / HIGHLIGHT_STEP as tunable meta — the exact oscillation
surface the plateau postmortem blamed. Here that surface is removed: the frozen
BOM-only header is a hard ``CONSTRAINTS_TO_PRESERVE`` entry the judge may never edit.
"""

from __future__ import annotations

import json
from typing import Any

from brickomancer.services.ldraw_writer import _BOM_META
from tests.harness._claude import HarnessLLMUnavailable, run_claude

# Dimension -> source file(s) the judge may target. Updated to the rebuilt modules
# (v1's image_pipeline/text_pipeline are gone; shapers replace them).
DIMENSION_SOURCE_FILES: dict[str, list[str]] = {
    "shape_fidelity": [
        "src/brickomancer/services/image_shaper.py",
        "src/brickomancer/services/text_shaper.py",
    ],
    "part_variety": ["src/brickomancer/services/brick_packer.py"],
    "build_stability": [
        "src/brickomancer/services/brick_packer.py",
        "src/brickomancer/services/ldraw_writer.py",
    ],
    "instruction_clarity": ["src/brickomancer/services/ldraw_writer.py"],
    "color_match": [
        "src/brickomancer/services/color_service.py",
        "src/brickomancer/services/suggestion_service.py",
    ],
    "aesthetics": [
        "src/brickomancer/services/suggestion_service.py",
        "src/brickomancer/utils/subprocess_utils.py",
    ],
    "pdf_completeness": [
        "src/brickomancer/services/ldraw_writer.py",
        "src/brickomancer/utils/subprocess_utils.py",
    ],
    "technical_validity": [
        "src/brickomancer/services/ldraw_writer.py",
        "src/brickomancer/services/brick_packer.py",
    ],
}

# Hard invariants the judge is FORBIDDEN to edit — the frozen-config layer that removes
# the v1 oscillation surface. The applier injects these into every change brief, and a
# change touching any of them must be rejected. The BOM-only meta header is the headline
# entry: ``0 !LPUB INSERT COVER_PAGE`` crashes LPub3D 2.4.9 (render-verified, Step 0.2 / 7).
CONSTRAINTS_TO_PRESERVE: frozenset[str] = frozenset(
    {
        # The frozen LPub3D meta header constant — render-verified; never edit.
        _BOM_META,
        "Never emit `0 !LPUB INSERT COVER_PAGE` — it crashes LPub3D 2.4.9 (blank/no PDF).",
        "The LPub3D meta header is FROZEN to BOM-only — no FADE_STEPS / HIGHLIGHT_STEP / "
        "COVER_PAGE churn (the v1 plateau oscillation surface).",
        "The `Shaper.to_voxels() -> (X, Y, Z)` bool-grid seam signature is fixed.",
        "The brick_packer connectivity-graph contract: 1 connected component, 0 unsupported.",
    }
)


def build_judge_prompt(report_text: str, history_text: str) -> str:
    """Build the judge change-brief prompt, injecting the frozen constraints as hard rules.

    The constraints block is what replaces v1's meta-tuning reference: rather than
    describing COVER_PAGE/FADE_STEPS as options, it forbids touching the frozen header.
    """
    valid_dimensions = sorted(DIMENSION_SOURCE_FILES)
    valid_paths = sorted({p for paths in DIMENSION_SOURCE_FILES.values() for p in paths})
    constraints_block = "\n".join(f"  - {c}" for c in sorted(CONSTRAINTS_TO_PRESERVE))

    return (
        "You are the judge for a loop that improves a LEGO instruction PDF generator.\n\n"
        "## Advisor report (this iteration)\n"
        f"{report_text}\n\n"
        "## Recent history\n"
        f"{history_text}\n\n"
        "## HARD CONSTRAINTS — never propose a change that violates any of these:\n"
        f"{constraints_block}\n\n"
        "## Your task\n"
        "Select the single most impactful dimension to improve next. Avoid oscillating "
        "dimensions (committed then reverted repeatedly). A change that edits any frozen "
        "constraint above is invalid — pick a different approach.\n\n"
        f"Valid dimensions: {valid_dimensions}\n"
        f"Valid file paths: {valid_paths}\n\n"
        "## Output\n"
        "Output ONLY valid JSON on a single line:\n"
        '{"dimension": "<str>", "file_path": "<one of the valid paths>", '
        '"rationale": "<str>", "approach_description": "<str>", '
        '"functions_to_modify": [], "constraints_to_preserve": [], '
        '"anti_patterns_to_avoid": [], "blocking_issues": [], "confidence": <0.0-1.0>}'
    )


_REQUIRED_FIELDS = {"dimension", "file_path", "approach_description"}


def _parse_decision(output: str) -> dict[str, Any] | None:
    """Extract + validate the judge's JSON decision (whole output, then brace-scan)."""
    candidates = [output]
    start, end = output.find("{"), output.rfind("}")
    if start != -1 and end > start:
        candidates.append(output[start : end + 1])
    valid_paths = {p for paths in DIMENSION_SOURCE_FILES.values() for p in paths}
    for text in candidates:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict) or not _REQUIRED_FIELDS.issubset(parsed):
            continue
        file_path = str(parsed["file_path"])
        # Refuse a file the judge is not allowed to touch — a hard guard on top of the
        # prompt's constraint block (the judge picks the file; the applier gate + these
        # bounds keep it inside the sanctioned surface).
        if file_path not in valid_paths:
            continue
        return {
            "dimension": str(parsed["dimension"]),
            "file_path": file_path,
            "rationale": str(parsed.get("rationale", "")),
            "approach_description": str(parsed["approach_description"]),
            "blocking_issues": [str(b) for b in parsed.get("blocking_issues", [])],
        }
    return None


def judge(
    report_text: str,
    history_text: str,
    *,
    run_claude_fn: Any = run_claude,
) -> dict[str, Any] | None:
    """Ask claude to pick the next change; return a validated decision or None.

    None (LLM unavailable / unparseable / out-of-bounds file) makes the loop skip the
    iteration rather than act on a malformed decision.
    """
    prompt = build_judge_prompt(report_text, history_text)
    try:
        output = run_claude_fn(prompt)
    except HarnessLLMUnavailable:
        return None
    return _parse_decision(output)

"""Judge: reads the full advisor report and decides what change to make next."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("harness")

JUDGE_TIMEOUT_S = 300

# Dimensions whose source files touch ldraw_writer.py — inject LPub3D reference into brief.
_LPUB_DIMENSIONS = {"pdf_completeness", "instruction_clarity", "technical_validity", "build_stability"}

DIMENSION_SOURCE_FILES: dict[str, list[str]] = {
    "shape_fidelity": ["src/brickomancer/services/image_pipeline.py"],
    "color_match": [
        "src/brickomancer/services/color_service.py",
        "src/brickomancer/services/suggestion_service.py",
    ],
    "build_stability": [
        "src/brickomancer/services/brick_packer.py",
        "src/brickomancer/services/ldraw_writer.py",
    ],
    "instruction_clarity": ["src/brickomancer/services/ldraw_writer.py"],
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
    "reference_fidelity": [
        "src/brickomancer/services/image_pipeline.py",
        "src/brickomancer/services/brick_packer.py",
    ],
}

LPUB3D_META_REFERENCE = """
LPub3D meta command reference (EXACT syntax required — wrong form produces blank PDFs):
  0 STEP                               — page break; insert after every build layer including the last
  0 !LPUB INSERT BOM                   — parts list page; place AFTER the final 0 STEP (stable — do not remove)
  0 !LPUB INSERT COVER_PAGE            — cover page; must appear AFTER a 0 STEP boundary, NOT before any bricks
  0 !LPUB FADE_STEPS ENABLED TRUE      — fade previously-placed bricks; goes in file header before first brick line
  0 !LPUB FADE_STEPS SETUP OPACITY 50  — set fade opacity 0-100; place immediately after FADE_STEPS ENABLED line
  0 !LPUB HIGHLIGHT_STEP ENABLED TRUE  — highlight newly-added bricks per step; goes in header before first brick
  0 !LPUB HIGHLIGHT_STEP SETUP COLOR 0000FF — highlight color as 6-char hex; after HIGHLIGHT_STEP ENABLED line
CAUTION: Multiple optional meta commands combined can cause blank pages. If pdf_completeness is 0, remove all
optional commands first (keep only 0 STEP and INSERT BOM), confirm pages render, then add one at a time.
"""

# Fields required in a valid judge decision.
_REQUIRED_FIELDS = {"dimension", "file_path", "rationale", "approach_description"}


def _validate_judge_decision(parsed: Any) -> dict[str, Any] | None:
    """Validate and normalise judge output. Returns None on bad shape."""
    if not isinstance(parsed, dict):
        return None
    if not _REQUIRED_FIELDS.issubset(parsed.keys()):
        return None
    dimension = str(parsed["dimension"])
    file_path = str(parsed["file_path"])
    if not dimension or not file_path:
        return None
    return {
        "dimension": dimension,
        "file_path": file_path,
        "rationale": str(parsed.get("rationale", "")),
        "approach_description": str(parsed.get("approach_description", "")),
        "functions_to_modify": [str(f) for f in parsed.get("functions_to_modify", [])],
        "constraints_to_preserve": [str(c) for c in parsed.get("constraints_to_preserve", [])],
        "anti_patterns_to_avoid": [str(a) for a in parsed.get("anti_patterns_to_avoid", [])],
        "blocking_issues": [str(b) for b in parsed.get("blocking_issues", [])],
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 1.0)))),
    }


def _parse_judge_output(output: str) -> dict[str, Any] | None:
    """Extract and validate judge JSON from Claude output."""
    try:
        parsed = json.loads(output)
        result = _validate_judge_decision(parsed)
        if result is not None:
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    # Scan from first '{' to last '}', working inward on failure
    start = output.find("{")
    if start == -1:
        return None
    end = output.rfind("}")
    while end > start:
        try:
            parsed = json.loads(output[start : end + 1])
            result = _validate_judge_decision(parsed)
            if result is not None:
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        end = output.rfind("}", 0, end)
    return None


def _format_advisor_report(advisor_results: dict[str, Any]) -> str:
    """Render the advisor report as a readable table for the judge prompt."""
    advisors = advisor_results.get("advisors", {})
    avg_raw = advisor_results.get("avg_raw")
    lines = [
        f"avg_raw={avg_raw:.3f}" if isinstance(avg_raw, float) else f"avg_raw={avg_raw}",
        "",
        "dimension          | raw | norm  | weight | findings",
        "-------------------|-----|-------|--------|--------",
    ]
    for aid, data in advisors.items():
        raw = str(data.get("score", "?")).rjust(3)
        norm = f"{data.get('normalized_score', 0.0):.2f}".rjust(5)
        weight = f"{data.get('weight', 0.0):.2f}".rjust(6)
        findings_preview = "; ".join(data.get("findings", []))[:80]
        lines.append(f"{aid:<18} | {raw} | {norm} | {weight} | {findings_preview}")
    return "\n".join(lines)


def _build_judge_prompt(
    advisor_results: dict[str, Any],
    scores_jsonl: Path,
    project_root: Path,
) -> str:
    report_text = _format_advisor_report(advisor_results)

    # History context (last 10 rows)
    history_lines: list[str] = []
    if scores_jsonl.exists():
        try:
            raw_lines = scores_jsonl.read_text(encoding="utf-8").splitlines()
            rows = [json.loads(ln) for ln in raw_lines[-10:] if ln.strip()]
            for row in rows:
                result = row.get("test_result", "?")
                dim = row.get("selected_dimension", "?")
                avg = row.get("avg_raw", "?")
                summary = (row.get("change_summary") or "(none)")[:100]
                tag = "COMMITTED" if result == "PASS_COMMITTED" else f"SKIPPED({result})"
                history_lines.append(f"  iter {row.get('iteration','?')}: [{tag}] dim={dim} avg={avg} — {summary}")
        except (OSError, json.JSONDecodeError):
            pass

    history_text = "\n".join(history_lines) if history_lines else "  (no history yet)"

    # warnings_judge findings get special prominence
    warnings_data = advisor_results.get("advisors", {}).get("warnings_judge", {})
    warnings_findings = warnings_data.get("findings", [])
    warnings_score = warnings_data.get("score", 10)
    warnings_section = ""
    if warnings_findings:
        w_lines = "\n".join(f"  - {f}" for f in warnings_findings)
        warnings_section = (
            f"\nWARNINGS JUDGE (score={warnings_score}/10 — lower=worse):\n{w_lines}\n"
            "If score <= 4, these warnings are dire and MUST influence your decision "
            "(e.g. avoid the oscillating dimension, pick a fresh approach).\n"
        )

    # Valid file paths (excluding warnings_judge from the dimension table)
    valid_dimensions = [d for d in DIMENSION_SOURCE_FILES]
    valid_paths = sorted({p for paths in DIMENSION_SOURCE_FILES.values() for p in paths})

    lpub_note = (
        "\nNote: if you select a dimension that maps to ldraw_writer.py, the applier will "
        "receive the LPub3D meta command reference as context.\n"
        + LPUB3D_META_REFERENCE
    )

    return (
        "You are the judge for an automated loop that improves a LEGO instruction PDF generator.\n\n"
        "## Advisor report (this iteration)\n"
        f"{report_text}\n\n"
        "## Recent history (last 10 iterations)\n"
        f"{history_text}\n"
        f"{warnings_section}\n"
        "## Your task\n"
        "Analyse the advisor findings and history. Select the single most impactful dimension to "
        "improve next. Avoid oscillating dimensions (committed then reverted repeatedly). "
        "If the warnings_judge score is <= 4, treat its findings as hard constraints.\n\n"
        "If blocking issues make any change inadvisable this iteration (e.g. all approaches have "
        "been tried and reverted, or the loop is in a confirmed oscillation), populate "
        "blocking_issues and leave approach_description empty — the applier will skip this iteration.\n\n"
        f"Valid dimensions: {valid_dimensions}\n"
        f"Valid file paths: {valid_paths}\n"
        f"{lpub_note}\n"
        "## Output\n"
        "Output ONLY valid JSON on a single line:\n"
        '{"dimension": "<str>", "file_path": "<one of the valid paths>", '
        '"rationale": "<why this dimension and file>", '
        '"approach_description": "<what specific change to make and how>", '
        '"functions_to_modify": ["<fn1>", ...], '
        '"constraints_to_preserve": ["<constraint1>", ...], '
        '"anti_patterns_to_avoid": ["<pattern1>", ...], '
        '"blocking_issues": [], '
        '"confidence": <float 0.0-1.0>}'
    )


def judge(
    advisor_results: dict[str, Any],
    scores_jsonl: Path,
    project_root: Path,
) -> dict[str, Any] | None:
    """Call Claude to decide the next change. Returns decision dict or None on failure."""
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        log.warning("CLAUDE_CODE_OAUTH_TOKEN not set — judge returning None")
        return None

    prompt = _build_judge_prompt(advisor_results, scores_jsonl, project_root)
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token}

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log.warning("judge timed out after %ds", JUDGE_TIMEOUT_S)
        return None
    except OSError as exc:
        log.warning("judge subprocess error: %s", exc)
        return None

    if proc.returncode != 0:
        log.warning("judge exited %d: %s", proc.returncode, proc.stderr[:200])
        return None

    decision = _parse_judge_output(proc.stdout.strip())
    if decision is None:
        log.warning("judge output unparseable: %s", proc.stdout[:300])
        # One retry asking for clean JSON
        retry_prompt = (
            "Your previous response was not valid JSON matching the required schema. "
            "Your response was:\n\n"
            f"{proc.stdout[:600]}\n\n"
            "Return ONLY a single line of valid JSON:\n"
            '{"dimension": "<str>", "file_path": "<str>", "rationale": "<str>", '
            '"approach_description": "<str>", "functions_to_modify": [], '
            '"constraints_to_preserve": [], "anti_patterns_to_avoid": [], '
            '"blocking_issues": [], "confidence": 1.0}'
        )
        try:
            retry = subprocess.run(
                ["claude", "-p", retry_prompt],
                capture_output=True, text=True, timeout=JUDGE_TIMEOUT_S, env=env,
            )
            decision = _parse_judge_output(retry.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass
        if decision is None:
            log.warning("judge unparseable after retry — skipping this iteration")
            return None

    blocking = decision.get("blocking_issues", [])
    if blocking:
        log.warning("judge raised blocking issues — applier will skip: %s", blocking)
    else:
        log.info(
            "judge decision: dim=%s file=%s (confidence=%.2f)",
            decision["dimension"], decision["file_path"], decision["confidence"],
        )

    return decision

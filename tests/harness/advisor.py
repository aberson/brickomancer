"""Advisor engine: run Claude advisors in parallel, score, and report."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("harness")

ADVISOR_TIMEOUT_S = 240

# LPub3D meta command reference injected into developer prompts for ldraw-touching dimensions.
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


def _validate_advisor_result(parsed: Any) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    score = parsed.get("score")
    confidence = parsed.get("confidence")
    findings = parsed.get("findings", [])
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    if not isinstance(findings, list):
        findings = []
    return {
        "score": max(0, min(10, int(score))),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "findings": [str(f) for f in findings],
    }


def _parse_advisor_output(output: str) -> dict[str, Any] | None:
    try:
        return _validate_advisor_result(json.loads(output))
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r'\{[^{}]*"score"[^{}]*\}', output, re.DOTALL)
    if match:
        try:
            return _validate_advisor_result(json.loads(match.group()))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _extract_parts_list(ldr_path: str) -> str:
    try:
        ldr_text = Path(ldr_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "[LDR file not readable]"
    counts: dict[str, int] = {}
    for line in ldr_text.splitlines():
        fields = line.strip().split()
        if len(fields) >= 15 and fields[0] == "1":
            part_file = fields[14]
            counts[part_file] = counts.get(part_file, 0) + 1
    if not counts:
        return "[No parts found in LDR file]"
    return "\n".join(f"{part}: {count}" for part, count in sorted(counts.items()))


def _normalize_scores(raw_scores: list[float]) -> list[float]:
    n = len(raw_scores)
    if n == 0:
        return []
    mean = sum(raw_scores) / n
    variance = sum((x - mean) ** 2 for x in raw_scores) / n
    std = math.sqrt(variance)
    if std == 0.0:
        return [5.0] * n
    result = []
    for raw in raw_scores:
        z = (raw - mean) / std
        norm = (z + 3.0) / 6.0 * 10.0
        result.append(round(max(0.0, min(10.0, norm)), 4))
    return result


def _compute_weights(normalized_scores: list[float], confidences: list[float]) -> list[float]:
    return [round(max(0.0, (10.0 - ns) * c), 4) for ns, c in zip(normalized_scores, confidences)]


def _format_scores_history(scores_jsonl: Path, n: int = 15) -> str:
    """Return a compact table of the last N score rows for injection into advisor prompts."""
    if not scores_jsonl.exists():
        return "[No score history available yet]"
    try:
        raw_lines = scores_jsonl.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(ln) for ln in raw_lines[-n:] if ln.strip()]
    except (OSError, json.JSONDecodeError):
        return "[Score history unreadable]"
    if not rows:
        return "[No score history available yet]"
    lines = ["iter | avg_raw | result            | dim                | summary"]
    lines.append("-----|---------|-------------------|--------------------|--------")
    for row in rows:
        it = str(row.get("iteration", "?")).rjust(4)
        avg = f"{row.get('avg_raw', '?'):.3f}" if isinstance(row.get("avg_raw"), float) else "  ?"
        result = (row.get("test_result") or "?")[:18].ljust(18)
        dim = (row.get("selected_dimension") or "?")[:18].ljust(18)
        summary = (row.get("change_summary") or "(none)")[:80]
        lines.append(f"{it} | {avg}  | {result} | {dim} | {summary}")
    return "\n".join(lines)


def _build_advisor_prompt(
    advisor: dict[str, Any],
    iteration_state: dict[str, Any],
    gold_step_final_path: Path,
    scores_jsonl: Path | None = None,
) -> str:
    reads: list[str] = advisor.get("reads", [])
    advisor_id: str = advisor["id"]
    parts: list[str] = [advisor["prompt"].strip()]

    if "scores_history" in reads:
        if scores_jsonl is not None:
            history_text = _format_scores_history(scores_jsonl)
        else:
            history_text = "[scores_jsonl not provided to advisor engine]"
        parts.append(f"\n\n--- Score history (last 15 iterations) ---\n{history_text}\n--- end score history ---")

    if "ldr_file" in reads or "parts_list" in reads:
        ldr_path = iteration_state.get("ldr_path", "")
        ldr_text = ""
        if ldr_path and Path(ldr_path).exists():
            try:
                ldr_text = Path(ldr_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                ldr_text = ""
        if "ldr_file" in reads:
            if ldr_text:
                lines = ldr_text.splitlines()
                truncated = len(lines) > 400
                display = "\n".join(lines[:400])
                suffix = f"\n[... truncated at 400/{len(lines)} lines ...]" if truncated else ""
                parts.append(f"\n\n--- LDraw file contents ---\n{display}{suffix}\n--- end of LDraw file ---")
            else:
                parts.append("\n\n[LDraw file not available for this iteration]")
        if "parts_list" in reads:
            parts_text = _extract_parts_list(ldr_path) if ldr_path else "[Parts list not available]"
            parts.append(f"\n\n--- Parts list (part_id: count) ---\n{parts_text}\n--- end of parts list ---")

    if "pdf" in reads or "pdf_first_page" in reads:
        pdf_path = iteration_state.get("pdf_path", "")
        if pdf_path:
            if "pdf" in reads:
                parts.append(
                    f"\n\nThe instruction PDF is at this absolute path: {pdf_path}\n"
                    "Use your Read tool to read and analyse the full PDF content."
                )
            if "pdf_first_page" in reads:
                parts.append(
                    f"\n\nThe instruction PDF is at this absolute path: {pdf_path}\n"
                    "Use your Read tool to read the first page (page 1) of the PDF."
                )

    if "preview_png" in reads:
        preview_png = iteration_state.get("preview_png_path")
        if preview_png and Path(preview_png).exists():
            parts.append(
                f"\n\nThe rendered LEGO preview image is at this absolute path: {preview_png}\n"
                "Use your Read tool to view this image."
            )
        else:
            log.warning("Advisor %s: preview_png not available", advisor_id)

    if "input_image" in reads:
        input_img_str = iteration_state.get("input_image_path")
        input_img = Path(input_img_str) if input_img_str else None
        if input_img and input_img.exists():
            parts.append(
                f"\n\nThe original input image is at this absolute path: {input_img}\n"
                "Use your Read tool to view this image."
            )
        else:
            log.warning("Advisor %s: input_image not available in iteration_state", advisor_id)

    if "gold_step_final" in reads:
        if gold_step_final_path.exists():
            parts.append(
                "\n\nThe gold-standard reference image (final step of an ideal build for this"
                f" input) is at this absolute path: {gold_step_final_path}\n"
                "Use your Read tool to view this reference image."
            )
        else:
            log.warning("Advisor %s: gold_step_final not found at %s", advisor_id, gold_step_final_path)

    return "".join(parts)


def _run_single_advisor(
    advisor: dict[str, Any],
    iteration_state: dict[str, Any],
    gold_step_final_path: Path,
    scores_jsonl: Path | None = None,
    timeout_s: int = ADVISOR_TIMEOUT_S,
) -> dict[str, Any]:
    advisor_id: str = advisor["id"]
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        log.warning("CLAUDE_CODE_OAUTH_TOKEN not set — advisor %s returning stub", advisor_id)
        return {"score": 5, "confidence": 0.0, "findings": ["ADVISOR_TOKEN_MISSING"]}

    full_prompt = _build_advisor_prompt(advisor, iteration_state, gold_step_final_path, scores_jsonl)
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token}
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log.warning("Advisor %s timed out after %ds", advisor_id, timeout_s)
        return {"score": 5, "confidence": 0.0, "findings": ["ADVISOR_TIMEOUT"]}
    except OSError as exc:
        log.warning("Advisor %s failed to start: %s", advisor_id, exc)
        return {"score": 5, "confidence": 0.0, "findings": [f"ADVISOR_ERROR: {exc}"]}

    if result.returncode != 0:
        log.warning("Advisor %s exited %d: %s", advisor_id, result.returncode, result.stderr[:200])
        return {"score": 5, "confidence": 0.0, "findings": [f"ADVISOR_SUBPROCESS_FAILED: exit={result.returncode}"]}

    parsed = _parse_advisor_output(result.stdout.strip())
    if parsed is None:
        log.warning("Advisor %s output unparseable: %s", advisor_id, result.stdout[:200])
        return {"score": 5, "confidence": 0.0, "findings": ["ADVISOR_PARSE_ERROR"]}

    return parsed


def advisor_engine(
    advisors_yaml: Path,
    gold_step_final_path: Path,
    runs_dir: Path,
    file_prefix: str,
    iteration_state: dict[str, Any],
    scores_jsonl: Path | None = None,
) -> dict[str, Any]:
    """Run all advisors in parallel, z-score normalise, compute weights, save report."""
    with advisors_yaml.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    advisors: list[dict[str, Any]] = config["advisors"]
    ordered_ids: list[str] = [a["id"] for a in advisors]

    log.info("advisor_engine: running %d advisors in parallel…", len(advisors))

    raw_results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
        future_to_id = {
            pool.submit(_run_single_advisor, advisor, iteration_state, gold_step_final_path, scores_jsonl): advisor["id"]
            for advisor in advisors
        }
        for future in concurrent.futures.as_completed(future_to_id):
            aid = future_to_id[future]
            try:
                raw_results[aid] = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("Advisor %s raised unexpectedly: %s", aid, exc)
                raw_results[aid] = {"score": 5, "confidence": 0.0, "findings": [f"ADVISOR_ERROR: {exc}"]}

    raw_scores = [float(raw_results[aid]["score"]) for aid in ordered_ids]
    confidences = [float(raw_results[aid]["confidence"]) for aid in ordered_ids]
    normalized = _normalize_scores(raw_scores)
    weights = _compute_weights(normalized, confidences)

    scores_raw = {aid: raw_results[aid]["score"] for aid in ordered_ids}
    scores_normalized = {aid: normalized[i] for i, aid in enumerate(ordered_ids)}
    scores_weights = {aid: weights[i] for i, aid in enumerate(ordered_ids)}
    avg_normalized = sum(normalized) / len(normalized) if normalized else None
    avg_raw = sum(raw_scores) / len(raw_scores) if raw_scores else None

    report: dict[str, Any] = {
        "scores_raw": scores_raw,
        "scores_normalized": scores_normalized,
        "weights": scores_weights,
        "avg_normalized": round(avg_normalized, 4) if avg_normalized is not None else None,
        "avg_raw": round(avg_raw, 4) if avg_raw is not None else None,
        "advisors": {
            aid: {
                "score": raw_results[aid]["score"],
                "confidence": raw_results[aid]["confidence"],
                "findings": raw_results[aid]["findings"],
                "normalized_score": scores_normalized[aid],
                "weight": scores_weights[aid],
            }
            for aid in ordered_ids
        },
    }

    report_path = runs_dir / f"{file_prefix}_advisor_reports.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("advisor_engine: saved report -> %s", report_path)

    return report

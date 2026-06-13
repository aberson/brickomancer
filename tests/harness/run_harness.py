"""Brickomancer evaluation harness.

Standalone script (not a pytest test).  Manages the server lifecycle,
runs N evaluation iterations, and appends structured results to scores.jsonl.

Usage:
    python tests/harness/run_harness.py [--iterations N] [--dry-run]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent
PROJECT_ROOT = HARNESS_DIR.parent.parent
TMP_DIR_PATH = PROJECT_ROOT / "tmp"
RUNS_DIR = HARNESS_DIR / "runs"
SCORES_JSONL = HARNESS_DIR / "scores.jsonl"
SERVER_LOG = HARNESS_DIR / "server.log"

SERVER_URL = "http://localhost:8005"
STATUS_URL = f"{SERVER_URL}/api/status"
POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 2.0
QUALITY_THRESHOLD = 8.0
ADVISORS_YAML = HARNESS_DIR / "advisors.yaml"
ADVISOR_TIMEOUT_S = 30

_INPUT_IMAGE_PATH = HARNESS_DIR.parent / "integration" / "fixtures" / "cake.jpg"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[HARNESS] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("harness")

# ---------------------------------------------------------------------------
# Stub functions (raise NotImplementedError until implemented)
# ---------------------------------------------------------------------------


def pipeline_executor(iteration_dir: Path) -> dict[str, Any]:
    """Run the full pipeline for one iteration and return iteration state.

    Steps:
    1. POST /api/generate/from-image with the cake.jpg fixture.
    2. Extract the compact suggestion from the response.
    3. POST /api/generate/instructions for the compact suggestion.
    4. Save the returned PDF to iteration_dir/instructions.pdf.
    5. Copy the preview PNG from tmp/<uuid_part>/suggestion_0_preview.png if present.
    6. Return a dict with iteration state for downstream advisors.
    """
    fixture_path = HARNESS_DIR.parent / "integration" / "fixtures" / "cake.jpg"

    # --- Step 1: POST /from-image ---
    with httpx.Client(timeout=300.0) as client:
        log.info("pipeline_executor: POSTing to /api/generate/from-image …")
        with fixture_path.open("rb") as img_fh:
            response = client.post(
                f"{SERVER_URL}/api/generate/from-image",
                files={"image": ("cake.jpg", img_fh, "image/jpeg")},
                data={"height_studs": "8"},
            )
        response.raise_for_status()
        generate_data: dict[str, Any] = response.json()

    # --- Step 2: Extract compact suggestion ---
    suggestions: list[dict[str, Any]] = generate_data.get("suggestions", [])
    compact_suggestion: dict[str, Any] | None = next(
        (s for s in suggestions if s.get("tier") == "compact"), None
    )
    if compact_suggestion is None:
        raise ValueError("No compact suggestion in response")

    suggestion_id: str = compact_suggestion["id"]
    # suggestion_id format: "<uuid>_0"  — split on last "_" to get uuid_part
    uuid_part, _tier_index = suggestion_id.rsplit("_", 1)

    # --- Step 3: POST /instructions ---
    with httpx.Client(timeout=120.0) as client:
        log.info(
            "pipeline_executor: POSTing to /api/generate/instructions (suggestion_id=%s) …",
            suggestion_id,
        )
        instr_response = client.post(
            f"{SERVER_URL}/api/generate/instructions",
            json={"suggestion_id": suggestion_id},
        )
        instr_response.raise_for_status()
        pdf_bytes = instr_response.content
        if not pdf_bytes:
            raise ValueError("instructions endpoint returned empty PDF bytes")

    # --- Step 4: Save PDF ---
    pdf_path = iteration_dir / "instructions.pdf"
    pdf_path.write_bytes(pdf_bytes)
    log.info("pipeline_executor: PDF saved → %s (%d bytes)", pdf_path, len(pdf_bytes))

    # --- Step 5: Copy preview PNG ---
    preview_src = TMP_DIR_PATH / uuid_part / "suggestion_0_preview.png"
    preview_dst = iteration_dir / "preview.png"
    if preview_src.exists():
        shutil.copy2(preview_src, preview_dst)
        log.info("pipeline_executor: Preview PNG copied → %s", preview_dst)
        preview_png_path = str(preview_dst)
    else:
        log.warning(
            "pipeline_executor: Preview PNG not found at %s — continuing without it.",
            preview_src,
        )
        preview_png_path = None

    # --- Step 6: LDR file path ---
    ldr_path = str(TMP_DIR_PATH / uuid_part / "suggestion_0.ldr")

    return {
        "suggestion_id": suggestion_id,
        "uuid_part": uuid_part,
        "ldr_path": ldr_path,
        "preview_png_path": preview_png_path,
        "pdf_path": str(pdf_path),
    }


def _validate_advisor_result(parsed: Any) -> dict[str, Any] | None:
    """Validate advisor JSON shape and clamp values. Returns None on bad input."""
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
    """Extract and validate JSON from advisor output. Returns None on failure."""
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
    """Parse LDR type-1 lines to produce a 'part_id: count' text block."""
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
    """Z-score normalise raw scores (population std), map to [0,10], clamp."""
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
    """Sampling weight per advisor: w = max(0, (10 − norm) × confidence)."""
    return [round(max(0.0, (10.0 - ns) * c), 4) for ns, c in zip(normalized_scores, confidences)]


def _run_single_advisor(
    advisor: dict[str, Any],
    iteration_state: dict[str, Any],
    timeout_s: int = ADVISOR_TIMEOUT_S,
) -> dict[str, Any]:
    """Invoke one advisor via `claude -p` subprocess and return parsed result."""
    advisor_id: str = advisor["id"]
    reads: list[str] = advisor.get("reads", [])
    base_prompt: str = advisor["prompt"].strip()

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        log.warning("CLAUDE_CODE_OAUTH_TOKEN not set — advisor %s returning stub", advisor_id)
        return {"score": 5, "confidence": 0.0, "findings": ["ADVISOR_TOKEN_MISSING"]}

    prompt_parts: list[str] = [base_prompt]

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
                prompt_parts.append(
                    f"\n\n--- LDraw file contents ---\n{ldr_text}\n--- end of LDraw file ---"
                )
            else:
                prompt_parts.append("\n\n[LDraw file not available for this iteration]")
        if "parts_list" in reads:
            parts_text = _extract_parts_list(ldr_path) if ldr_path else "[Parts list not available]"
            prompt_parts.append(
                f"\n\n--- Parts list (part_id: count) ---\n{parts_text}\n--- end of parts list ---"
            )

    if "pdf" in reads or "pdf_first_page" in reads:
        pdf_path = iteration_state.get("pdf_path", "")
        if pdf_path:
            if "pdf" in reads:
                prompt_parts.append(
                    f"\n\nThe instruction PDF is at this absolute path: {pdf_path}\n"
                    "Use your Read tool to read and analyse the full PDF content."
                )
            if "pdf_first_page" in reads:
                prompt_parts.append(
                    f"\n\nThe instruction PDF is at this absolute path: {pdf_path}\n"
                    "Use your Read tool to read the first page (page 1) of the PDF."
                )

    full_prompt = "".join(prompt_parts)
    cmd: list[str] = ["claude", "-p", full_prompt]

    if "preview_png" in reads:
        preview_png = iteration_state.get("preview_png_path")
        if preview_png and Path(preview_png).exists():
            cmd += ["--image", preview_png]
        else:
            log.warning("Advisor %s: preview_png not available — omitting --image", advisor_id)

    if "input_image" in reads:
        if _INPUT_IMAGE_PATH.exists():
            cmd += ["--image", str(_INPUT_IMAGE_PATH)]
        else:
            log.warning(
                "Advisor %s: input_image fixture not found at %s", advisor_id, _INPUT_IMAGE_PATH
            )

    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
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
        log.warning(
            "Advisor %s exited %d: %s", advisor_id, result.returncode, result.stderr[:200]
        )
        return {
            "score": 5,
            "confidence": 0.0,
            "findings": [f"ADVISOR_SUBPROCESS_FAILED: exit={result.returncode}"],
        }

    parsed = _parse_advisor_output(result.stdout.strip())
    if parsed is None:
        log.warning("Advisor %s output unparseable: %s", advisor_id, result.stdout[:200])
        return {"score": 5, "confidence": 0.0, "findings": ["ADVISOR_PARSE_ERROR"]}

    return parsed


def advisor_engine(iteration_dir: Path, iteration_state: dict[str, Any]) -> dict[str, Any]:
    """Run all advisors in parallel and return a scored results report.

    Loads advisors.yaml, spawns 7 parallel claude -p calls, applies z-score
    normalisation, computes sampling weights, saves advisor_reports.json to
    iteration_dir, and returns the report dict.
    """
    with ADVISORS_YAML.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    advisors: list[dict[str, Any]] = config["advisors"]
    ordered_ids: list[str] = [a["id"] for a in advisors]

    log.info("advisor_engine: running %d advisors in parallel…", len(advisors))

    raw_results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        future_to_id = {
            pool.submit(_run_single_advisor, advisor, iteration_state): advisor["id"]
            for advisor in advisors
        }
        for future in concurrent.futures.as_completed(future_to_id):
            aid = future_to_id[future]
            try:
                raw_results[aid] = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("Advisor %s raised unexpectedly: %s", aid, exc)
                raw_results[aid] = {
                    "score": 5,
                    "confidence": 0.0,
                    "findings": [f"ADVISOR_ERROR: {exc}"],
                }

    raw_scores = [float(raw_results[aid]["score"]) for aid in ordered_ids]
    confidences = [float(raw_results[aid]["confidence"]) for aid in ordered_ids]
    normalized = _normalize_scores(raw_scores)
    weights = _compute_weights(normalized, confidences)

    scores_raw = {aid: raw_results[aid]["score"] for aid in ordered_ids}
    scores_normalized = {aid: normalized[i] for i, aid in enumerate(ordered_ids)}
    scores_weights = {aid: weights[i] for i, aid in enumerate(ordered_ids)}
    avg_normalized = sum(normalized) / len(normalized) if normalized else None

    report: dict[str, Any] = {
        "scores_raw": scores_raw,
        "scores_normalized": scores_normalized,
        "weights": scores_weights,
        "avg_normalized": round(avg_normalized, 4) if avg_normalized is not None else None,
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

    report_path = iteration_dir / "advisor_reports.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("advisor_engine: saved report → %s", report_path)

    return report


def developer_agent(advisor_results: dict[str, Any], iteration: int) -> dict[str, Any]:
    """Use advisor results to propose and apply code/config improvements."""
    raise NotImplementedError("developer_agent is not yet implemented")


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def _start_server(log_path: Path) -> subprocess.Popen[bytes]:
    """Spawn the uvicorn server and return the Popen handle."""
    os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\Tools\LPub3D"
    log_fh = log_path.open("wb")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "--app-dir",
            "src",
            "brickomancer.main:app",
            "--port",
            "8005",
        ],
        stdout=log_fh,
        stderr=log_fh,
    )
    log.info("Server process started (pid=%d); log → %s", proc.pid, log_path)
    return proc


def _wait_for_server(timeout_s: float = POLL_TIMEOUT_S) -> bool:
    """Poll /api/status until ldview_ok and lpub3d_ok are True, or timeout.

    Returns True on success, False on timeout.
    """
    deadline = time.monotonic() + timeout_s
    log.info("Waiting for server to become ready (timeout=%ss)…", int(timeout_s))
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(STATUS_URL, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ldview_ok") and data.get("lpub3d_ok"):
                    log.info("Server ready: ldview_ok=True lpub3d_ok=True")
                    return True
                log.info(
                    "Server up but not ready yet: ldview_ok=%s lpub3d_ok=%s",
                    data.get("ldview_ok"),
                    data.get("lpub3d_ok"),
                )
        except httpx.HTTPError:
            pass
        time.sleep(POLL_INTERVAL_S)
    log.error("Server did not become ready within %ss", int(timeout_s))
    return False


def _terminate_server(proc: subprocess.Popen[bytes] | None) -> None:
    """Terminate the server process, forcibly killing if needed."""
    if proc is None:
        return
    log.info("Terminating server process (pid=%d)…", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=10)
        log.info("Server process exited cleanly.")
    except subprocess.TimeoutExpired:
        log.warning("Server did not exit in 10s — sending kill.")
        proc.kill()
        proc.wait()
        log.info("Server process killed.")


# ---------------------------------------------------------------------------
# Scores helpers
# ---------------------------------------------------------------------------


def _append_scores(entry: dict[str, Any]) -> None:
    """Append a JSON line to scores.jsonl."""
    with SCORES_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _dry_run_scores_entry(iteration: int) -> dict[str, Any]:
    return {
        "iteration": iteration,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "scores_raw": {},
        "scores_normalized": {},
        "selected_dimension": None,
        "change_summary": None,
        "test_result": None,
        "avg_normalized": None,
        "dry_run": True,
    }


def _scores_entry(
    iteration: int,
    advisor_results: dict[str, Any],
    dev_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "iteration": iteration,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "scores_raw": advisor_results.get("scores_raw", {}),
        "scores_normalized": advisor_results.get("scores_normalized", {}),
        "selected_dimension": dev_result.get("selected_dimension"),
        "change_summary": dev_result.get("change_summary"),
        "test_result": dev_result.get("test_result"),
        "avg_normalized": advisor_results.get("avg_normalized"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Brickomancer evaluation harness")
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        metavar="N",
        help="Number of evaluation iterations to run (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip server start and API calls; create directories and stub scores only",
    )
    args = parser.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    proc: subprocess.Popen[bytes] | None = None
    iterations_completed = 0

    try:
        if not args.dry_run:
            proc = _start_server(SERVER_LOG)
            ready = _wait_for_server()
            if not ready:
                log.error("Aborting: server never became ready.")
                sys.exit(1)

        for i in range(1, args.iterations + 1):
            iteration_dir = RUNS_DIR / f"iteration_{i}"
            iteration_dir.mkdir(parents=True, exist_ok=True)
            log.info("--- Iteration %d/%d ---", i, args.iterations)

            if args.dry_run:
                _append_scores(_dry_run_scores_entry(i))
                iterations_completed += 1
                continue

            # a) Run pipeline
            iteration_state = pipeline_executor(iteration_dir)

            # b) Run advisors
            advisor_results = advisor_engine(iteration_dir, iteration_state)

            # c) Check quality threshold
            avg = advisor_results.get("avg_normalized")
            if avg is not None and avg > QUALITY_THRESHOLD:
                log.info(
                    "Advisors suggest quality target met (%.1f/10) — continuing to iteration %d/%d",
                    avg,
                    i,
                    args.iterations,
                )

            # d) Developer agent
            dev_result = developer_agent(advisor_results, i)

            # e) Append scores
            _append_scores(_scores_entry(i, advisor_results, dev_result))
            iterations_completed += 1

    finally:
        if proc is not None:
            _terminate_server(proc)
        log.info("Summary: %d/%d iterations completed.", iterations_completed, args.iterations)


if __name__ == "__main__":
    main()

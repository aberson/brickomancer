"""Brickomancer evaluation harness.

Standalone script (not a pytest test).  Manages the server lifecycle,
runs N evaluation iterations, and appends structured results to scores.jsonl.

Usage:
    python tests/harness/run_harness.py [--iterations N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from tests.harness.advisor import advisor_engine
from tests.harness.applier import apply
from tests.harness.judge import judge
from tests.harness.pipeline import pick_input_image, pipeline_executor
from tests.harness.server import start_server, terminate_server, wait_for_server

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent
PROJECT_ROOT = HARNESS_DIR.parent.parent
TMP_DIR_PATH = PROJECT_ROOT / "tmp"
RUNS_DIR = HARNESS_DIR / "runs"
SCORES_JSONL = HARNESS_DIR / "scores.jsonl"
SERVER_LOG = HARNESS_DIR / "server.log"
ADVISORS_YAML = HARNESS_DIR / "advisors.yaml"

SERVER_PORT = 8005
SERVER_URL = f"http://localhost:{SERVER_PORT}"
STATUS_URL = f"{SERVER_URL}/api/status"

QUALITY_THRESHOLD = 8.0
_HEIGHT_STUDS = 5
_INPUT_IMAGE_DIR = PROJECT_ROOT / "docs" / "example_input_output" / "star" / "input_image"
GOLD_STEP_FINAL_PATH = (
    PROJECT_ROOT / "docs" / "example_input_output" / "star" / "step_output" / "star_step_10.png"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="[HARNESS] %(message)s", stream=sys.stdout)
log = logging.getLogger("harness")

# ---------------------------------------------------------------------------
# Scores helpers
# ---------------------------------------------------------------------------


def _append_scores(entry: dict) -> None:
    with SCORES_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _patch_advisor_report(runs_dir: Path, file_prefix: str, extra: dict) -> None:
    """Merge extra keys into the existing advisor report JSON in-place."""
    report_path = runs_dir / f"{file_prefix}_advisor_reports.json"
    if not report_path.exists():
        return
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        data.update(extra)
        report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("_patch_advisor_report: could not update %s: %s", report_path.name, exc)


def _dry_run_scores_entry(iteration: int) -> dict:
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
    advisor_results: dict,
    apply_result: dict,
    judge_decision: dict | None = None,
    input_image_name: str | None = None,
    height_studs: int | None = None,
) -> dict:
    return {
        "iteration": iteration,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "input_image": input_image_name,
        "height_studs": height_studs,
        "scores_raw": advisor_results.get("scores_raw", {}),
        "scores_normalized": advisor_results.get("scores_normalized", {}),
        "selected_dimension": apply_result.get("dimension"),
        "change_summary": apply_result.get("change_summary"),
        "test_result": apply_result.get("test_result"),
        "avg_normalized": advisor_results.get("avg_normalized"),
        "avg_raw": advisor_results.get("avg_raw"),
        "judge_rationale": judge_decision.get("rationale") if judge_decision else None,
        "judge_blocking": judge_decision.get("blocking_issues") if judge_decision else None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Brickomancer evaluation harness")
    parser.add_argument("--iterations", type=int, default=5, metavar="N",
                        help="Number of evaluation iterations to run (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip server start and API calls; create directories and stub scores only")
    args = parser.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    proc = None
    iterations_completed = 0

    try:
        if not args.dry_run:
            proc = start_server(SERVER_PORT, SERVER_LOG)
            if not wait_for_server(STATUS_URL):
                log.error("Aborting: server never became ready.")
                sys.exit(1)

        for i in range(1, args.iterations + 1):
            ts = datetime.now().strftime("%H%M")
            file_prefix = f"i{i}_{ts}"
            log.info("--- Iteration %d/%d ---", i, args.iterations)

            if args.dry_run:
                _append_scores(_dry_run_scores_entry(i))
                iterations_completed += 1
                continue

            # a) Pipeline
            input_image_path = pick_input_image(_INPUT_IMAGE_DIR)
            log.info("Selected input image: %s, height_studs: %d", input_image_path.name, _HEIGHT_STUDS)
            iteration_state = pipeline_executor(
                SERVER_URL, TMP_DIR_PATH, RUNS_DIR, file_prefix, input_image_path, _HEIGHT_STUDS
            )

            # b) Advisors (includes warnings_judge)
            advisor_results = advisor_engine(
                ADVISORS_YAML, GOLD_STEP_FINAL_PATH, RUNS_DIR, file_prefix,
                iteration_state, scores_jsonl=SCORES_JSONL,
            )

            # c) Quality gate
            avg = advisor_results.get("avg_raw")
            if avg is not None and avg >= QUALITY_THRESHOLD:
                log.info(
                    "Quality threshold reached (avg raw %.2f >= %.1f) — stopping after iteration %d.",
                    avg, QUALITY_THRESHOLD, i,
                )
                _append_scores(_scores_entry(
                    i, advisor_results, {"test_result": "QUALITY_GATE_MET"},
                    input_image_name=input_image_path.name, height_studs=_HEIGHT_STUDS,
                ))
                iterations_completed += 1
                break

            # d) Judge
            log.info("Running judge…")
            judge_decision = judge(advisor_results, SCORES_JSONL, PROJECT_ROOT)
            if judge_decision is None:
                log.warning("Judge returned None — recording SKIPPED_JUDGE_FAILED and continuing.")
                _append_scores(_scores_entry(
                    i, advisor_results, {"test_result": "SKIPPED_JUDGE_FAILED"},
                    input_image_name=input_image_path.name, height_studs=_HEIGHT_STUDS,
                ))
                iterations_completed += 1
                continue

            _patch_advisor_report(RUNS_DIR, file_prefix, {"judge_decision": judge_decision})

            # e) Applier
            apply_result = apply(judge_decision, i, PROJECT_ROOT)
            _patch_advisor_report(RUNS_DIR, file_prefix, {
                "apply_result": {
                    "test_result": apply_result.get("test_result"),
                    "change_summary": apply_result.get("change_summary"),
                    "dimension": apply_result.get("dimension"),
                }
            })
            _append_scores(_scores_entry(
                i, advisor_results, apply_result, judge_decision,
                input_image_path.name, _HEIGHT_STUDS,
            ))
            iterations_completed += 1

            # f) Restart server if code was committed
            if apply_result.get("test_result") == "PASS_COMMITTED" and i < args.iterations:
                log.info("Code committed — restarting server to pick up changes…")
                terminate_server(proc)
                proc = start_server(SERVER_PORT, SERVER_LOG)
                if not wait_for_server(STATUS_URL):
                    log.error("Server failed to restart after commit — aborting.")
                    break

    finally:
        if proc is not None:
            terminate_server(proc)
        log.info("Summary: %d/%d iterations completed.", iterations_completed, args.iterations)


if __name__ == "__main__":
    main()

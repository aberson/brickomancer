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
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent
RUNS_DIR = HARNESS_DIR / "runs"
SCORES_JSONL = HARNESS_DIR / "scores.jsonl"
SERVER_LOG = HARNESS_DIR / "server.log"

SERVER_URL = "http://localhost:8005"
STATUS_URL = f"{SERVER_URL}/api/status"
POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 2.0
QUALITY_THRESHOLD = 8.0

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
    """Run the full pipeline for one iteration and return iteration state."""
    raise NotImplementedError("pipeline_executor is not yet implemented")


def advisor_engine(iteration_dir: Path, iteration_state: dict[str, Any]) -> dict[str, Any]:
    """Run all advisors against the iteration artifacts and return scored results."""
    raise NotImplementedError("advisor_engine is not yet implemented")


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

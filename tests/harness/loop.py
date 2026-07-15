"""Calibration loop: judge -> developer -> render-score gate, N times (Phase 4, Step 10).

Ties the Step 9 pieces into the unattended hill-climb the plateau postmortem prescribes:

    baseline = render_and_score(eval set)
    repeat N times:
        report  = current per-dimension scores (lowest first = the judge's targets)
        decision = judge(report, history)              # pick a dimension + file + approach
        content  = developer(decision, current file)   # write the change
        result   = apply_change(...)   # apply -> pytest -> RE-SCORE -> commit|revert
        log row to scores.jsonl; ratchet the baseline up on a committed improvement

The commit gate is the Step 9 applier: a change ships ONLY if pytest passes AND no scored
dimension regresses below the ratcheted baseline. Every step is injectable so the loop is
dry-testable (test_loop.py) without the slow real claude+render path.

Run the real calibration (SLOW — real claude + render per eval item):
    $env:CLAUDE_CODE_OAUTH_TOKEN = `
        [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN","User")
    $env:PATH += ";C:\\Tools\\LPub3D"
    uv run python -m tests.harness.loop --iterations 5
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.harness import scorer
from tests.harness.applier import Change, _run_pytest, apply_change
from tests.harness.developer import write_change
from tests.harness.judge import judge

Scores = dict[str, float]

_DEFAULT_LOG = Path("tests/harness/scores.jsonl")


def _avg(scores: Scores | None) -> float | None:
    if not scores:
        return None
    return sum(scores.values()) / len(scores)


def _format_report(scores: Scores) -> str:
    """Per-dimension score table, lowest first (the judge's most-impactful targets)."""
    lines = ["dimension            | score", "---------------------|------"]
    for dim, val in sorted(scores.items(), key=lambda kv: kv[1]):
        lines.append(f"{dim:<20} | {val:5.2f}")
    avg = _avg(scores)
    lines.append(f"\navg_raw = {avg:.3f}" if avg is not None else "avg_raw = n/a")
    lines.append("(Pick a dimension shown above — those are the scored ones.)")
    return "\n".join(lines)


def _format_history(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "  (no history yet)"
    out = []
    for r in rows[-10:]:
        committed = r["test_result"] == "PASS_COMMITTED"
        tag = "COMMITTED" if committed else f"SKIPPED({r['test_result']})"
        out.append(
            f"  iter {r['iteration']}: [{tag}] dim={r['selected_dimension']} "
            f"avg={r['avg_raw']} — {(r['change_summary'] or '')[:80]}"
        )
    return "\n".join(out)


def _log(log_path: Path, row: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), **row}
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def run_calibration(
    iterations: int,
    project_root: str | Path,
    *,
    log_path: str | Path | None = None,
    judge_fn: Callable[..., dict[str, Any] | None] = judge,
    developer_fn: Callable[..., tuple[str, str] | None] = write_change,
    render_and_score: Callable[[str], Scores] = scorer.render_and_score,
    run_tests: Callable[..., Any] = _run_pytest,
) -> dict[str, Any]:
    """Run the calibration loop and return the trajectory summary.

    Returns ``{baseline_avg, final_avg, committed, rows}``. Every iteration appends one row
    to ``scores.jsonl`` (plus a baseline row), so a killed run still leaves its partial
    trajectory on disk.
    """
    root = Path(project_root)
    log = Path(log_path) if log_path is not None else root / _DEFAULT_LOG

    baseline_scores = render_and_score(str(root))
    baseline_avg = _avg(baseline_scores)
    _log(log, {"iteration": 0, "selected_dimension": None, "test_result": "BASELINE",
               "change_summary": None, "scores": baseline_scores, "avg_raw": baseline_avg})

    rows: list[dict[str, Any]] = []
    for i in range(1, iterations + 1):
        decision = judge_fn(_format_report(baseline_scores), _format_history(rows))
        if decision is None or decision.get("blocking_issues"):
            result_tag, summary, scores = "SKIPPED_JUDGE", None, None
        else:
            target = root / decision["file_path"]
            if not target.exists():
                result_tag, summary, scores = "SKIPPED_FILE_NOT_FOUND", None, None
            else:
                current = target.read_text(encoding="utf-8")
                dev = developer_fn(decision, current)
                if dev is None:
                    result_tag, summary, scores = "SKIPPED_DEV", None, None
                elif dev[0] == current:
                    # No-op developer output: skip rather than attempt an empty commit.
                    result_tag, summary, scores = "SKIPPED_NODIFF", dev[1], None
                else:
                    content, summary = dev
                    result = apply_change(
                        Change(decision["file_path"], content, decision["dimension"], summary),
                        project_root=root,
                        baseline_scores=baseline_scores,
                        iteration=i,
                        run_tests=run_tests,
                        render_and_score=render_and_score,
                    )
                    result_tag, scores = result.test_result, result.scores

        row = {
            "iteration": i,
            "selected_dimension": decision["dimension"] if decision else None,
            "test_result": result_tag,
            "change_summary": summary,
            "scores": scores,
            "avg_raw": _avg(scores),
        }
        _log(log, row)
        rows.append(row)
        # Ratchet the baseline up only on a committed improvement.
        if result_tag == "PASS_COMMITTED" and scores:
            baseline_scores = scores

    committed = [r for r in rows if r["test_result"] == "PASS_COMMITTED"]
    return {
        "baseline_avg": baseline_avg,
        "final_avg": _avg(baseline_scores),
        "committed": len(committed),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Brickomancer calibration loop.")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--project-root", type=str, default=".")
    args = parser.parse_args()

    summary = run_calibration(args.iterations, args.project_root)
    print("\n=== calibration trajectory ===")
    for r in summary["rows"]:
        print(f"  iter {r['iteration']}: {r['test_result']:24} "
              f"dim={r['selected_dimension']} avg_raw={r['avg_raw']}")
    print(f"baseline avg_raw={summary['baseline_avg']} -> final avg_raw={summary['final_avg']} "
          f"({summary['committed']} committed)")


if __name__ == "__main__":
    main()

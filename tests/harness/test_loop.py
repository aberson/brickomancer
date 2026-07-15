"""Dry-test of the calibration loop (Step 10) — no real claude / render / GPU.

Proves the orchestration end-to-end with injected fakes: the loop iterates, appends a
baseline + one row per iteration to scores.jsonl, commits improvements, reverts score
regressions (the Step 9 gate), and skips cleanly when the judge returns None. This is the
fast proof that lets the real (~90 min, source-mutating) calibration launch safely.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.harness import scorer
from tests.harness.loop import run_calibration

_TARGET = "src/brickomancer/services/brick_packer.py"  # a valid DIMENSION_SOURCE_FILES path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A git repo with the judge's target file committed as the baseline."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "harness@test")
    _git(tmp_path, "config", "user.name", "harness")
    target = tmp_path / _TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def _tests_pass(_root: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0)


def _judge_ok(_report: str, _history: str, **_kw: Any) -> dict[str, Any]:
    return {
        "dimension": "part_variety",
        "file_path": _TARGET,
        "approach_description": "raise it",
        "blocking_issues": [],
    }


def _dev_ok(_decision: dict[str, Any], _content: str, **_kw: Any) -> tuple[str, str]:
    return ("VALUE = 2\n", "bumped the value")


class _DevBump:
    """A developer that writes DISTINCT content each call (a real per-iteration diff)."""

    def __init__(self) -> None:
        self.n = 1

    def __call__(self, _decision: dict[str, Any], _content: str, **_kw: Any) -> tuple[str, str]:
        self.n += 1
        return (f"VALUE = {self.n}\n", f"set to {self.n}")


def _rows(log_path: Path) -> list[dict[str, Any]]:
    text = log_path.read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def _commit_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(repo), capture_output=True, text=True
    )
    return int(out.stdout.strip())


class _RisingScorer:
    """Each call scores higher — every iteration is a genuine improvement -> commits."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _root: str) -> dict[str, float]:
        self.calls += 1
        v = 5.0 + self.calls
        return {d: v for d in scorer.SCORE_DIMENSIONS}


class _DroppingScorer:
    """Baseline high, then every apply scores low -> every iteration regresses -> reverts."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _root: str) -> dict[str, float]:
        self.calls += 1
        v = 8.0 if self.calls == 1 else 2.0
        return {d: v for d in scorer.SCORE_DIMENSIONS}


def test_loop_commits_improvements_and_logs(repo: Path) -> None:
    log = repo / "scores.jsonl"
    summary = run_calibration(
        3, repo, log_path=log,
        judge_fn=_judge_ok, developer_fn=_DevBump(),
        render_and_score=_RisingScorer(), run_tests=_tests_pass,
    )
    rows = _rows(log)
    assert rows[0]["test_result"] == "BASELINE"
    assert len(rows) == 4  # baseline + 3 iterations
    assert all(r["test_result"] == "PASS_COMMITTED" for r in rows[1:])
    # avg_raw trends strictly up across the committed iterations.
    avgs = [r["avg_raw"] for r in rows]
    assert avgs == sorted(avgs) and avgs[-1] > avgs[0]
    assert summary["committed"] == 3
    assert _commit_count(repo) == 1 + 3  # baseline + one per committed iteration
    assert (repo / _TARGET).read_text(encoding="utf-8") == "VALUE = 4\n"


def test_loop_reverts_regressions(repo: Path) -> None:
    log = repo / "scores.jsonl"
    summary = run_calibration(
        2, repo, log_path=log,
        judge_fn=_judge_ok, developer_fn=_dev_ok,
        render_and_score=_DroppingScorer(), run_tests=_tests_pass,
    )
    rows = _rows(log)
    assert all(r["test_result"] == "SKIPPED_SCORE_REGRESSION" for r in rows[1:])
    assert summary["committed"] == 0
    assert _commit_count(repo) == 1  # nothing committed
    assert (repo / _TARGET).read_text(encoding="utf-8") == "VALUE = 1\n"  # reverted


def test_loop_skips_when_judge_returns_none(repo: Path) -> None:
    log = repo / "scores.jsonl"
    run_calibration(
        2, repo, log_path=log,
        judge_fn=lambda *a, **k: None, developer_fn=_dev_ok,
        render_and_score=_RisingScorer(), run_tests=_tests_pass,
    )
    rows = _rows(log)
    assert all(r["test_result"] == "SKIPPED_JUDGE" for r in rows[1:])
    assert _commit_count(repo) == 1


def test_loop_skips_nodiff_developer_output(repo: Path) -> None:
    """A developer that returns the current content unchanged -> SKIPPED_NODIFF, no commit."""
    log = repo / "scores.jsonl"
    run_calibration(
        1, repo, log_path=log,
        judge_fn=_judge_ok,
        developer_fn=lambda _d, content, **_k: (content, "no change"),
        render_and_score=_RisingScorer(), run_tests=_tests_pass,
    )
    rows = _rows(log)
    assert rows[1]["test_result"] == "SKIPPED_NODIFF"
    assert _commit_count(repo) == 1

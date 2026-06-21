"""Applier: the render-score regression gate (Step 9).

The defining change from v1 (docs/rebuild_reference/applier.py, gate at lines 210-237):
v1 committed on ``pytest green``. Here, pytest-green is necessary but NOT sufficient — a
change is committed only if, after pytest passes, re-rendering and re-scoring the eval set
shows **no score regression** vs the committed baseline; otherwise it is reverted. This is
the rung the plateau postmortem identified as missing.

``run_tests`` and ``render_and_score`` are injectable so the regression-gate test drives
the gate deterministically (fast fakes) while the real pipeline stays the default.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from tests.harness import scorer

# A change is "no worse" if every dimension is >= baseline and the average does not drop,
# within this tolerance (avoids float-noise reverts).
_SCORE_EPSILON: float = 1e-9

Scores = dict[str, float]


@dataclass(frozen=True)
class Change:
    """A ready-to-apply change to a single repo-relative file."""

    file_path: str
    content: str
    dimension: str = "unknown"
    summary: str = ""


@dataclass(frozen=True)
class ApplyResult:
    """Outcome of running a change through the gate."""

    dimension: str
    change_summary: str
    test_result: str  # PASS_COMMITTED | SKIPPED_SCORE_REGRESSION | SKIPPED_REVERT | SKIPPED_EMPTY
    scores: Scores | None = None
    commit: str | None = None


def _run_pytest(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "pytest", "-q", "--tb=short", "--ignore=tests/integration"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(project_root),
    )


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def _regressed(new_scores: Scores, baseline_scores: Scores | None) -> bool:
    """True if any dimension dropped below its baseline OR the average dropped.

    With no baseline (first iteration) nothing can regress.
    """
    if not baseline_scores:
        return False
    for dim, base in baseline_scores.items():
        if new_scores.get(dim, 0.0) < base - _SCORE_EPSILON:
            return True
    return _mean(new_scores.values()) < _mean(baseline_scores.values()) - _SCORE_EPSILON


def _revert(project_root: Path, rel_path: str) -> None:
    subprocess.run(
        ["git", "checkout", "--", rel_path],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )


def _git_commit(project_root: Path, rel_path: str, iteration: int, dimension: str) -> str | None:
    subprocess.run(
        ["git", "add", rel_path], capture_output=True, text=True, cwd=str(project_root)
    )
    commit = subprocess.run(
        ["git", "commit", "-m", f"harness iter {iteration}: improve {dimension}"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if commit.returncode != 0:
        return None
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    return head.stdout.strip() or None


def apply_change(
    change: Change,
    *,
    project_root: str | Path,
    baseline_scores: Scores | None,
    iteration: int = 0,
    run_tests: Callable[[Path], subprocess.CompletedProcess[str]] = _run_pytest,
    render_and_score: Callable[[str], Scores] = scorer.render_and_score,
) -> ApplyResult:
    """Apply a change through the two-stage gate; commit only on no regression.

    Stage 1 (necessary, not sufficient): unit tests must pass.
    Stage 2 (the v1-missing rung): re-render + re-score; no dimension may drop below the
    committed baseline and the average may not fall. On either stage failing, the file is
    reverted and nothing is committed.
    """
    root = Path(project_root)
    if not change.content:
        return ApplyResult(change.dimension, change.summary, "SKIPPED_EMPTY")

    (root / change.file_path).write_text(change.content, encoding="utf-8")

    # Stage 1 — unit tests.
    if run_tests(root).returncode != 0:
        _revert(root, change.file_path)
        return ApplyResult(change.dimension, change.summary, "SKIPPED_REVERT")

    # Stage 2 — re-render + re-score regression gate.
    new_scores = render_and_score(str(root))
    if _regressed(new_scores, baseline_scores):
        _revert(root, change.file_path)
        return ApplyResult(
            change.dimension, change.summary, "SKIPPED_SCORE_REGRESSION", new_scores
        )

    commit = _git_commit(root, change.file_path, iteration, change.dimension)
    return ApplyResult(change.dimension, change.summary, "PASS_COMMITTED", new_scores, commit)

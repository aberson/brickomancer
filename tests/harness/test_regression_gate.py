"""Regression-gate test (Phase 4, Step 9 done-when).

The explicit "real regression caught" exercise the plan requires: prove the applier's
render-score gate REVERTS a change that worsens the rendered output even when unit tests
pass, COMMITS a genuine improvement, and that the frozen meta header is a constraint the
judge may never edit. The render + pytest are injected as deterministic fakes so the gate
logic is tested fast (no real 17-min render).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brickomancer.services.ldraw_writer import _BOM_META
from tests.harness import judge
from tests.harness.applier import Change, apply_change

_BASELINE: dict[str, float] = {
    "pdf_completeness": 6.0,
    "technical_validity": 10.0,
    "build_stability": 10.0,
    "part_variety": 8.0,
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(repo), check=True
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A fresh git repo with one committed target file (the baseline)."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "harness@test")
    _git(tmp_path, "config", "user.name", "harness")
    (tmp_path / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "target.py")
    _git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def _tests_pass(_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0)


def _tests_fail(_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1)


def _commit_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True, cwd=str(repo)
    )
    return int(out.stdout.strip())


def _is_clean(repo: Path) -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(repo)
    )
    return out.stdout.strip() == ""


# --- (b1) a bad change that blanks the render is REJECTED/REVERTED by the score gate ---


def test_score_regression_is_reverted(repo: Path) -> None:
    """pytest passes, but the rendered PDF blanks (pdf_completeness -> 0) -> revert, no commit."""
    blanked = dict(_BASELINE, pdf_completeness=0.0, technical_validity=0.0)
    result = apply_change(
        Change("target.py", "VALUE = 999\n", dimension="pdf_completeness", summary="bad"),
        project_root=repo,
        baseline_scores=_BASELINE,
        run_tests=_tests_pass,
        render_and_score=lambda _root: blanked,
    )
    assert result.test_result == "SKIPPED_SCORE_REGRESSION"
    assert result.commit is None
    assert _commit_count(repo) == 1, "no commit should have been made"
    assert (repo / "target.py").read_text(encoding="utf-8") == "VALUE = 1\n", "file not reverted"
    assert _is_clean(repo), "working tree not restored"


# --- (b2) a genuine improvement is COMMITTED ---


def test_improvement_is_committed(repo: Path) -> None:
    """pytest passes and every dimension holds/improves -> commit."""
    improved = {dim: base + 1.0 for dim, base in _BASELINE.items()}
    result = apply_change(
        Change("target.py", "VALUE = 2\n", dimension="part_variety", summary="good"),
        project_root=repo,
        baseline_scores=_BASELINE,
        run_tests=_tests_pass,
        render_and_score=lambda _root: improved,
    )
    assert result.test_result == "PASS_COMMITTED"
    assert result.commit is not None
    assert _commit_count(repo) == 2, "improvement should add one commit"
    assert (repo / "target.py").read_text(encoding="utf-8") == "VALUE = 2\n"


# --- (b3) the frozen meta header is a constraint the judge may never edit ---


def test_frozen_meta_header_in_constraints() -> None:
    assert _BOM_META in judge.CONSTRAINTS_TO_PRESERVE
    assert any("COVER_PAGE" in c for c in judge.CONSTRAINTS_TO_PRESERVE), (
        "the no-COVER_PAGE rule must be a preserved constraint"
    )


# --- bonus: pytest failure alone also reverts (stage-1 gate still holds) ---


def test_pytest_failure_is_reverted(repo: Path) -> None:
    result = apply_change(
        Change("target.py", "VALUE = 3\n", summary="breaks tests"),
        project_root=repo,
        baseline_scores=_BASELINE,
        run_tests=_tests_fail,
        render_and_score=lambda _root: dict(_BASELINE),
    )
    assert result.test_result == "SKIPPED_REVERT"
    assert _commit_count(repo) == 1
    assert (repo / "target.py").read_text(encoding="utf-8") == "VALUE = 1\n"

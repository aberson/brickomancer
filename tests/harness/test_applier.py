"""Unit tests for applier.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tests.harness.applier import _parse_applier_output, apply

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHANGED_FILE = "src/brickomancer/services/image_pipeline.py"

VALID_DECISION: dict[str, Any] = {
    "dimension": "shape_fidelity",
    "file_path": CHANGED_FILE,
    "rationale": "Star arms too thin",
    "approach_description": "Lower OR-pool threshold",
    "functions_to_modify": ["_extrude_silhouette"],
    "constraints_to_preserve": ["shape must be (X, height_studs, Z)"],
    "anti_patterns_to_avoid": [],
    "blocking_issues": [],
    "confidence": 0.9,
}

BLOCKING_DECISION: dict[str, Any] = {
    **VALID_DECISION,
    "blocking_issues": ["oscillation confirmed on pdf_completeness"],
}

APPLIER_JSON = json.dumps({"content": "# improved\n", "summary": "Lowered threshold"})


def _mock_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _setup_source_file(base: Path) -> Path:
    target = base / CHANGED_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# placeholder\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# _parse_applier_output
# ---------------------------------------------------------------------------


class TestParseApplierOutput:
    def test_clean_json(self) -> None:
        result = _parse_applier_output(APPLIER_JSON)
        assert result is not None
        assert result["content"] == "# improved\n"
        assert result["summary"] == "Lowered threshold"

    def test_json_embedded_in_prose(self) -> None:
        output = f"Here is the change:\n{APPLIER_JSON}\nDone."
        result = _parse_applier_output(output)
        assert result is not None
        assert "content" in result

    def test_missing_content_key_returns_none(self) -> None:
        assert _parse_applier_output('{"summary": "oops"}') is None

    def test_garbage_returns_none(self) -> None:
        assert _parse_applier_output("not json") is None


# ---------------------------------------------------------------------------
# apply — blocking / token / file-not-found guards
# ---------------------------------------------------------------------------


class TestApplyGuards:
    def test_blocking_issues_skips_without_claude_call(self, tmp_path: Path) -> None:
        with patch("tests.harness.applier.subprocess.run") as mock_run:
            result = apply(BLOCKING_DECISION, iteration=1, project_root=tmp_path)
        assert result["test_result"] == "SKIPPED_BLOCKED"
        mock_run.assert_not_called()

    def test_no_token_returns_skipped(self, tmp_path: Path) -> None:
        _setup_source_file(tmp_path)
        import os
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            with patch("tests.harness.applier.subprocess.run") as mock_run:
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)
        assert result["test_result"] == "SKIPPED_NO_TOKEN"
        mock_run.assert_not_called()

    def test_missing_file_returns_skipped(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.applier.subprocess.run") as mock_run:
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)
        assert result["test_result"] == "SKIPPED_FILE_NOT_FOUND"
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# apply — happy path (commit)
# ---------------------------------------------------------------------------


class TestApplyCommitPath:
    def test_commit_path_writes_file_and_commits(self, tmp_path: Path) -> None:
        target = _setup_source_file(tmp_path)

        side_effects = [
            _mock_proc(0, stdout=APPLIER_JSON),  # claude
            _mock_proc(0, stdout="5 passed"),    # pytest
            _mock_proc(0),                        # git add
            _mock_proc(0),                        # git commit
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.applier.subprocess.run", side_effect=side_effects) as mock_run:
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)

        assert result["test_result"] == "PASS_COMMITTED"
        assert result["dimension"] == "shape_fidelity"
        assert result["change_summary"] == "Lowered threshold"
        assert target.read_text() == "# improved\n"
        assert mock_run.call_count == 4
        commit_cmd = mock_run.call_args_list[3].args[0]
        assert "commit" in commit_cmd
        assert "judge" in " ".join(commit_cmd)

    def test_claude_timeout_returns_skipped(self, tmp_path: Path) -> None:
        _setup_source_file(tmp_path)

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch(
                "tests.harness.applier.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600),
            ):
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)

        assert result["test_result"] == "SKIPPED_TIMEOUT"


# ---------------------------------------------------------------------------
# apply — revert path
# ---------------------------------------------------------------------------


class TestApplyRevertPath:
    def test_pytest_failure_triggers_revert(self, tmp_path: Path) -> None:
        _setup_source_file(tmp_path)

        side_effects = [
            _mock_proc(0, stdout=APPLIER_JSON),     # claude
            _mock_proc(1, stderr="FAILED"),          # pytest fails
            _mock_proc(0, stdout="not json"),        # claude fix retry — unparseable
            _mock_proc(0),                           # git checkout
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.applier.subprocess.run", side_effect=side_effects) as mock_run:
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)

        assert result["test_result"] == "SKIPPED_REVERT"
        last_cmd = mock_run.call_args_list[3].args[0]
        assert "checkout" in last_cmd

    def test_fix_retry_success_commits(self, tmp_path: Path) -> None:
        _setup_source_file(tmp_path)
        fix_json = json.dumps({"content": "# fixed\n", "summary": "Fixed tests"})

        side_effects = [
            _mock_proc(0, stdout=APPLIER_JSON),     # claude (initial)
            _mock_proc(1, stderr="FAILED"),          # pytest fails
            _mock_proc(0, stdout=fix_json),          # claude fix retry
            _mock_proc(0, stdout="5 passed"),        # pytest retry passes
            _mock_proc(0),                           # git add
            _mock_proc(0),                           # git commit
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.applier.subprocess.run", side_effect=side_effects) as mock_run:
                result = apply(VALID_DECISION, iteration=1, project_root=tmp_path)

        assert result["test_result"] == "PASS_COMMITTED"
        assert result["change_summary"] == "Fixed tests"
        assert mock_run.call_count == 6

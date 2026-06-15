"""Unit and integration tests for developer_agent helpers.

Covers:
- _select_dimension: weighted sampling, zero-weight uniform fallback
- _parse_developer_output: valid JSON, prose-embedded JSON, garbage
- developer_agent integration: commit path, revert path, timeout, no-token
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tests.harness.run_harness import (
    DIMENSION_SOURCE_FILES,
    _parse_developer_output,
    _select_dimension,
    developer_agent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_ADVISOR_IDS = list(DIMENSION_SOURCE_FILES.keys())


def _fake_advisor_results(top_dim: str, top_weight: float = 10.0) -> dict[str, Any]:
    """Build a fake advisor_results dict that deterministically selects top_dim."""
    weights = {aid: (top_weight if aid == top_dim else 0.0) for aid in ALL_ADVISOR_IDS}
    advisors = {
        aid: {
            "score": 3,
            "confidence": 1.0,
            "findings": [f"{aid} finding"],
            "normalized_score": 2.0,
            "weight": weights[aid],
        }
        for aid in ALL_ADVISOR_IDS
    }
    return {
        "scores_raw": {aid: 3 for aid in ALL_ADVISOR_IDS},
        "scores_normalized": {aid: 2.0 for aid in ALL_ADVISOR_IDS},
        "weights": weights,
        "avg_normalized": 2.0,
        "advisors": advisors,
    }


def _mock_subprocess(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# _select_dimension
# ---------------------------------------------------------------------------


class TestSelectDimension:
    def test_all_weight_on_one_dimension(self) -> None:
        weights = {aid: (10.0 if aid == "color_match" else 0.0) for aid in ALL_ADVISOR_IDS}
        assert _select_dimension(weights) == "color_match"

    def test_zero_total_weight_still_returns_an_id(self) -> None:
        weights = {aid: 0.0 for aid in ALL_ADVISOR_IDS}
        result = _select_dimension(weights)
        assert result in ALL_ADVISOR_IDS

    def test_empty_dict_raises(self) -> None:
        import pytest

        with pytest.raises((IndexError, ValueError, KeyError)):
            _select_dimension({})

    def test_single_dimension(self) -> None:
        assert _select_dimension({"shape_fidelity": 5.0}) == "shape_fidelity"


# ---------------------------------------------------------------------------
# _parse_developer_output
# ---------------------------------------------------------------------------


class TestParseDeveloperOutput:
    def test_clean_json(self) -> None:
        payload = {
            "changes": [{"file_path": "src/a.py", "content": "# new\n"}],
            "summary": "Added feature",
        }
        result = _parse_developer_output(json.dumps(payload))
        assert result is not None
        assert result["changes"][0]["file_path"] == "src/a.py"

    def test_json_embedded_in_prose(self) -> None:
        payload = {
            "changes": [{"file_path": "src/b.py", "content": "x=1\n"}],
            "summary": "Fix",
        }
        output = f"Here is my change:\n{json.dumps(payload)}\nDone."
        result = _parse_developer_output(output)
        assert result is not None
        assert result["summary"] == "Fix"

    def test_missing_changes_key_returns_none(self) -> None:
        assert _parse_developer_output('{"summary": "oops"}') is None

    def test_garbage_returns_none(self) -> None:
        assert _parse_developer_output("not json") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_developer_output("") is None


# ---------------------------------------------------------------------------
# developer_agent integration
# ---------------------------------------------------------------------------


def _setup_source_files(base: Path) -> None:
    """Create stub source files mirroring DIMENSION_SOURCE_FILES under base."""
    seen: set[str] = set()
    for paths in DIMENSION_SOURCE_FILES.values():
        for rel in paths:
            if rel not in seen:
                seen.add(rel)
                target = base / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# placeholder\n", encoding="utf-8")


class TestDeveloperAgentIntegration:
    def test_commit_path(self, tmp_path: Path) -> None:
        """When pytest passes, developer_agent commits the change."""
        _setup_source_files(tmp_path)
        advisor_results = _fake_advisor_results("shape_fidelity")

        changed_file = "src/brickomancer/services/image_pipeline.py"
        dev_json = json.dumps({
            "changes": [{"file_path": changed_file, "content": "# improved\n"}],
            "summary": "Added gradient voxelization",
        })

        side_effects = [
            _mock_subprocess(0, stdout=dev_json),   # claude
            _mock_subprocess(0, stdout="5 passed"),  # pytest
            _mock_subprocess(0),                     # git add
            _mock_subprocess(0),                     # git commit
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.run_harness.PROJECT_ROOT", tmp_path):
                with patch(
                    "tests.harness.run_harness.subprocess.run", side_effect=side_effects
                ) as mock_run:
                    result = developer_agent(advisor_results, iteration=1)

        assert result["test_result"] == "PASS_COMMITTED"
        assert result["selected_dimension"] == "shape_fidelity"
        assert result["change_summary"] == "Added gradient voxelization"

        # Verify the changed file was written
        written = (tmp_path / changed_file).read_text()
        assert written == "# improved\n"

        # Verify subprocess call order: claude, pytest, git add, git commit
        assert mock_run.call_count == 4
        first_cmd = mock_run.call_args_list[0].args[0]
        assert first_cmd[0] == "claude"
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "pytest" in second_cmd

    def test_revert_path(self, tmp_path: Path) -> None:
        """When pytest fails and fix retry also fails to parse, developer_agent reverts."""
        _setup_source_files(tmp_path)
        advisor_results = _fake_advisor_results("shape_fidelity")

        changed_file = "src/brickomancer/services/image_pipeline.py"
        dev_json = json.dumps({
            "changes": [{"file_path": changed_file, "content": "# broken\n"}],
            "summary": "Broke something",
        })

        side_effects = [
            _mock_subprocess(0, stdout=dev_json),      # claude (initial)
            _mock_subprocess(1, stderr="FAILED"),      # pytest fails
            _mock_subprocess(0, stdout="not json"),    # claude fix retry — unparseable
            _mock_subprocess(0),                       # git checkout (revert)
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.run_harness.PROJECT_ROOT", tmp_path):
                with patch(
                    "tests.harness.run_harness.subprocess.run", side_effect=side_effects
                ) as mock_run:
                    result = developer_agent(advisor_results, iteration=1)

        assert result["test_result"] == "SKIPPED_REVERT"
        assert result["selected_dimension"] == "shape_fidelity"

        # claude, pytest, claude-fix-retry, git checkout
        assert mock_run.call_count == 4
        last_cmd = mock_run.call_args_list[3].args[0]
        assert "checkout" in last_cmd

    def test_revert_path_fix_retry_success(self, tmp_path: Path) -> None:
        """When pytest fails but fix retry produces valid code, the fixed version commits."""
        _setup_source_files(tmp_path)
        advisor_results = _fake_advisor_results("shape_fidelity")

        changed_file = "src/brickomancer/services/image_pipeline.py"
        dev_json = json.dumps({
            "changes": [{"file_path": changed_file, "content": "# broken\n"}],
            "summary": "Added feature but broke test",
        })
        fix_json = json.dumps({
            "changes": [{"file_path": changed_file, "content": "# fixed\n"}],
            "summary": "Fixed test breakage",
        })

        side_effects = [
            _mock_subprocess(0, stdout=dev_json),      # claude (initial)
            _mock_subprocess(1, stderr="FAILED"),      # pytest fails
            _mock_subprocess(0, stdout=fix_json),      # claude fix retry — valid
            _mock_subprocess(0, stdout="5 passed"),    # pytest retry passes
            _mock_subprocess(0),                       # git add
            _mock_subprocess(0),                       # git commit
        ]

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.run_harness.PROJECT_ROOT", tmp_path):
                with patch(
                    "tests.harness.run_harness.subprocess.run", side_effect=side_effects
                ) as mock_run:
                    result = developer_agent(advisor_results, iteration=1)

        assert result["test_result"] == "PASS_COMMITTED"
        assert result["change_summary"] == "Fixed test breakage"
        assert mock_run.call_count == 6
        written = (tmp_path / changed_file).read_text()
        assert written == "# fixed\n"

    def test_no_token_returns_early(self, tmp_path: Path) -> None:
        """Without CLAUDE_CODE_OAUTH_TOKEN, developer_agent returns SKIPPED_NO_TOKEN."""
        advisor_results = _fake_advisor_results("color_match")

        with patch.dict("os.environ", {}, clear=True):
            # Remove token if present
            import os
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
            with patch.dict("os.environ", env, clear=True):
                with patch("tests.harness.run_harness.PROJECT_ROOT", tmp_path):
                    with patch("tests.harness.run_harness.subprocess.run") as mock_run:
                        result = developer_agent(advisor_results, iteration=1)

        assert result["test_result"] == "SKIPPED_NO_TOKEN"
        mock_run.assert_not_called()

    def test_claude_timeout_returns_skipped(self, tmp_path: Path) -> None:
        """When the claude subprocess times out, developer_agent returns SKIPPED_TIMEOUT."""
        _setup_source_files(tmp_path)
        advisor_results = _fake_advisor_results("color_match")

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch("tests.harness.run_harness.PROJECT_ROOT", tmp_path):
                with patch(
                    "tests.harness.run_harness.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
                ):
                    result = developer_agent(advisor_results, iteration=1)

        assert result["test_result"] == "SKIPPED_TIMEOUT"
        assert result["change_summary"] is None

"""Unit tests for judge.py helpers and integration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tests.harness.judge import (
    _build_judge_prompt,
    _format_advisor_report,
    _parse_judge_output,
    _validate_judge_decision,
    judge,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_DECISION = {
    "dimension": "shape_fidelity",
    "file_path": "src/brickomancer/services/image_pipeline.py",
    "rationale": "Star arms collapsed to blobs",
    "approach_description": "Lower OR-pool threshold to 0.15",
    "functions_to_modify": ["_extrude_silhouette"],
    "constraints_to_preserve": ["shape must be (X, height_studs, Z)"],
    "anti_patterns_to_avoid": ["do not change camera angle"],
    "blocking_issues": [],
    "confidence": 0.9,
}

BLOCKING_DECISION = {**VALID_DECISION, "blocking_issues": ["oscillation detected on pdf_completeness"]}


def _fake_advisor_results(warnings_score: int = 8) -> dict[str, Any]:
    dims = [
        "shape_fidelity", "color_match", "build_stability", "instruction_clarity",
        "aesthetics", "pdf_completeness", "technical_validity", "reference_fidelity",
        "warnings_judge",
    ]
    scores = {d: (warnings_score if d == "warnings_judge" else 5) for d in dims}
    return {
        "scores_raw": scores,
        "scores_normalized": {d: 5.0 for d in dims},
        "weights": {d: 5.0 for d in dims},
        "avg_raw": 5.0,
        "avg_normalized": 5.0,
        "advisors": {
            d: {
                "score": scores[d],
                "confidence": 0.8,
                "findings": [f"{d} finding"],
                "normalized_score": 5.0,
                "weight": 5.0,
            }
            for d in dims
        },
    }


def _mock_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# _validate_judge_decision
# ---------------------------------------------------------------------------


class TestValidateJudgeDecision:
    def test_valid_full_decision(self) -> None:
        result = _validate_judge_decision(VALID_DECISION)
        assert result is not None
        assert result["dimension"] == "shape_fidelity"
        assert result["blocking_issues"] == []
        assert isinstance(result["functions_to_modify"], list)

    def test_missing_required_field_returns_none(self) -> None:
        bad = {k: v for k, v in VALID_DECISION.items() if k != "rationale"}
        assert _validate_judge_decision(bad) is None

    def test_non_dict_returns_none(self) -> None:
        assert _validate_judge_decision("string") is None
        assert _validate_judge_decision(None) is None
        assert _validate_judge_decision([1, 2]) is None

    def test_optional_lists_default_to_empty(self) -> None:
        minimal = {
            "dimension": "color_match",
            "file_path": "src/brickomancer/services/color_service.py",
            "rationale": "Colors wrong",
            "approach_description": "Fix KMeans init",
        }
        result = _validate_judge_decision(minimal)
        assert result is not None
        assert result["functions_to_modify"] == []
        assert result["constraints_to_preserve"] == []
        assert result["blocking_issues"] == []

    def test_confidence_clamped(self) -> None:
        d = {**VALID_DECISION, "confidence": 99.0}
        result = _validate_judge_decision(d)
        assert result is not None
        assert result["confidence"] == 1.0

    def test_blocking_decision_valid(self) -> None:
        result = _validate_judge_decision(BLOCKING_DECISION)
        assert result is not None
        assert len(result["blocking_issues"]) == 1


# ---------------------------------------------------------------------------
# _parse_judge_output
# ---------------------------------------------------------------------------


class TestParseJudgeOutput:
    def test_clean_json(self) -> None:
        result = _parse_judge_output(json.dumps(VALID_DECISION))
        assert result is not None
        assert result["dimension"] == "shape_fidelity"

    def test_json_embedded_in_prose(self) -> None:
        output = f"Here is my decision:\n{json.dumps(VALID_DECISION)}\nThat is all."
        result = _parse_judge_output(output)
        assert result is not None

    def test_garbage_returns_none(self) -> None:
        assert _parse_judge_output("not json at all") is None

    def test_json_missing_required_field_returns_none(self) -> None:
        bad = {k: v for k, v in VALID_DECISION.items() if k != "dimension"}
        assert _parse_judge_output(json.dumps(bad)) is None


# ---------------------------------------------------------------------------
# _format_advisor_report
# ---------------------------------------------------------------------------


class TestFormatAdvisorReport:
    def test_contains_all_dimensions(self) -> None:
        results = _fake_advisor_results()
        text = _format_advisor_report(results)
        assert "shape_fidelity" in text
        assert "warnings_judge" in text

    def test_contains_avg_raw(self) -> None:
        results = _fake_advisor_results()
        text = _format_advisor_report(results)
        assert "avg_raw" in text


# ---------------------------------------------------------------------------
# _build_judge_prompt
# ---------------------------------------------------------------------------


class TestBuildJudgePrompt:
    def test_warnings_section_included_when_low_score(self, tmp_path: Path) -> None:
        results = _fake_advisor_results(warnings_score=2)
        scores_jsonl = tmp_path / "scores.jsonl"
        prompt = _build_judge_prompt(results, scores_jsonl, tmp_path)
        assert "WARNINGS JUDGE" in prompt
        assert "dire" in prompt.lower() or "score=" in prompt

    def test_no_warnings_section_when_no_findings(self, tmp_path: Path) -> None:
        results = _fake_advisor_results(warnings_score=9)
        # Clear findings so the warnings section is suppressed
        results["advisors"]["warnings_judge"]["findings"] = []
        scores_jsonl = tmp_path / "scores.jsonl"
        prompt = _build_judge_prompt(results, scores_jsonl, tmp_path)
        assert "WARNINGS JUDGE" not in prompt

    def test_history_injected_from_scores_jsonl(self, tmp_path: Path) -> None:
        scores_jsonl = tmp_path / "scores.jsonl"
        entry = {
            "iteration": 1, "avg_raw": 4.5, "test_result": "PASS_COMMITTED",
            "selected_dimension": "color_match", "change_summary": "Fixed KMeans",
        }
        scores_jsonl.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        results = _fake_advisor_results()
        prompt = _build_judge_prompt(results, scores_jsonl, tmp_path)
        assert "color_match" in prompt
        assert "Fixed KMeans" in prompt


# ---------------------------------------------------------------------------
# judge integration
# ---------------------------------------------------------------------------


class TestJudgeIntegration:
    def test_happy_path_returns_decision(self, tmp_path: Path) -> None:
        advisor_results = _fake_advisor_results()
        scores_jsonl = tmp_path / "scores.jsonl"

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch(
                "tests.harness.judge.subprocess.run",
                return_value=_mock_proc(0, stdout=json.dumps(VALID_DECISION)),
            ):
                result = judge(advisor_results, scores_jsonl, tmp_path)

        assert result is not None
        assert result["dimension"] == "shape_fidelity"
        assert result["blocking_issues"] == []

    def test_blocking_issues_returned(self, tmp_path: Path) -> None:
        advisor_results = _fake_advisor_results()
        scores_jsonl = tmp_path / "scores.jsonl"

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch(
                "tests.harness.judge.subprocess.run",
                return_value=_mock_proc(0, stdout=json.dumps(BLOCKING_DECISION)),
            ):
                result = judge(advisor_results, scores_jsonl, tmp_path)

        assert result is not None
        assert len(result["blocking_issues"]) == 1

    def test_no_token_returns_none(self, tmp_path: Path) -> None:
        import os
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            result = judge(_fake_advisor_results(), tmp_path / "s.jsonl", tmp_path)
        assert result is None

    def test_timeout_returns_none(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch(
                "tests.harness.judge.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300),
            ):
                result = judge(_fake_advisor_results(), tmp_path / "s.jsonl", tmp_path)
        assert result is None

    def test_unparseable_output_retries_and_returns_none_on_second_failure(
        self, tmp_path: Path
    ) -> None:
        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake"}):
            with patch(
                "tests.harness.judge.subprocess.run",
                return_value=_mock_proc(0, stdout="not json"),
            ):
                result = judge(_fake_advisor_results(), tmp_path / "s.jsonl", tmp_path)
        assert result is None

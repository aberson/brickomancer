"""Unit tests for advisor_engine helpers and integration.

Covers:
- _normalize_scores: z-score normalisation, edge cases
- _compute_weights: weight formula w = (10 - norm) × confidence
- _parse_advisor_output: JSON extraction from raw Claude output
- _validate_advisor_result: type checking and value clamping
- _extract_parts_list: LDR type-1 line parsing
- advisor_engine integration: mocked subprocess, report structure
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tests.harness.advisor import (
    _compute_weights,
    _extract_parts_list,
    _normalize_scores,
    _parse_advisor_output,
    _validate_advisor_result,
    advisor_engine,
)
from tests.harness.run_harness import ADVISORS_YAML, GOLD_STEP_FINAL_PATH

# ---------------------------------------------------------------------------
# _normalize_scores
# ---------------------------------------------------------------------------


class TestNormalizeScores:
    def test_empty_list(self) -> None:
        assert _normalize_scores([]) == []

    def test_single_value_uses_std_zero_path(self) -> None:
        assert _normalize_scores([7.0]) == [5.0]

    def test_all_same_values(self) -> None:
        assert _normalize_scores([4.0, 4.0, 4.0]) == [5.0, 5.0, 5.0]

    def test_known_two_values(self) -> None:
        # [0, 10]: mean=5, pop_std=5
        # z(0)=-1 → (−1+3)/6×10 = 3.333…
        # z(10)=+1 → (1+3)/6×10  = 6.666…
        result = _normalize_scores([0.0, 10.0])
        assert len(result) == 2
        assert math.isclose(result[0], 10.0 / 3.0, rel_tol=1e-4)
        assert math.isclose(result[1], 20.0 / 3.0, rel_tol=1e-4)

    def test_extreme_outlier_clamped_to_ten(self) -> None:
        result = _normalize_scores([0.0, 0.0, 0.0, 10.0, 100.0])
        for v in result:
            assert 0.0 <= v <= 10.0

    def test_length_preserved(self) -> None:
        scores = [1.0, 3.0, 5.0, 7.0, 9.0, 2.0, 6.0]
        assert len(_normalize_scores(scores)) == 7

    def test_mean_score_maps_near_five(self) -> None:
        # For a symmetric distribution, the central value (mean) → 5.0
        result = _normalize_scores([0.0, 5.0, 10.0])
        assert math.isclose(result[1], 5.0, abs_tol=0.01)


# ---------------------------------------------------------------------------
# _compute_weights
# ---------------------------------------------------------------------------


class TestComputeWeights:
    def test_basic_formula(self) -> None:
        norms = [0.0, 5.0, 10.0]
        confs = [1.0, 0.5, 1.0]
        result = _compute_weights(norms, confs)
        assert math.isclose(result[0], 10.0)
        assert math.isclose(result[1], 2.5)
        assert math.isclose(result[2], 0.0)

    def test_no_negative_weights(self) -> None:
        result = _compute_weights([10.0, 10.0], [1.0, 1.0])
        assert all(w >= 0.0 for w in result)

    def test_zero_confidence_gives_zero_weight(self) -> None:
        assert _compute_weights([3.0, 7.0], [0.0, 0.0]) == [0.0, 0.0]

    def test_empty(self) -> None:
        assert _compute_weights([], []) == []


# ---------------------------------------------------------------------------
# _validate_advisor_result
# ---------------------------------------------------------------------------


class TestValidateAdvisorResult:
    def test_valid_result_passthrough(self) -> None:
        result = _validate_advisor_result(
            {"score": 7, "confidence": 0.9, "findings": ["good interlocking"]}
        )
        assert result is not None
        assert result["score"] == 7
        assert math.isclose(result["confidence"], 0.9)
        assert result["findings"] == ["good interlocking"]

    def test_score_clamped_to_ten(self) -> None:
        result = _validate_advisor_result({"score": 15, "confidence": 0.5, "findings": []})
        assert result is not None
        assert result["score"] == 10

    def test_score_clamped_to_zero(self) -> None:
        result = _validate_advisor_result({"score": -3, "confidence": 0.5, "findings": []})
        assert result is not None
        assert result["score"] == 0

    def test_missing_confidence_returns_none(self) -> None:
        assert _validate_advisor_result({"score": 5, "findings": []}) is None

    def test_non_dict_returns_none(self) -> None:
        assert _validate_advisor_result("not a dict") is None
        assert _validate_advisor_result([1, 2, 3]) is None
        assert _validate_advisor_result(None) is None

    def test_missing_findings_defaults_to_empty_list(self) -> None:
        result = _validate_advisor_result({"score": 5, "confidence": 0.8})
        assert result is not None
        assert result["findings"] == []

    def test_boolean_score_rejected(self) -> None:
        assert _validate_advisor_result({"score": True, "confidence": 0.5, "findings": []}) is None


# ---------------------------------------------------------------------------
# _parse_advisor_output
# ---------------------------------------------------------------------------


class TestParseAdvisorOutput:
    def test_clean_json_line(self) -> None:
        output = '{"score": 7, "confidence": 0.9, "findings": ["clear steps"]}'
        result = _parse_advisor_output(output)
        assert result is not None
        assert result["score"] == 7

    def test_json_embedded_in_prose(self) -> None:
        output = (
            "Here is my evaluation:\n"
            '{"score": 5, "confidence": 0.7, "findings": ["test finding"]}\n'
            "End of response."
        )
        result = _parse_advisor_output(output)
        assert result is not None
        assert result["score"] == 5

    def test_pure_garbage_returns_none(self) -> None:
        assert _parse_advisor_output("not json at all") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_advisor_output("") is None


# ---------------------------------------------------------------------------
# _extract_parts_list
# ---------------------------------------------------------------------------


class TestExtractPartsList:
    def test_parses_type1_lines(self, tmp_path: Path) -> None:
        ldr = tmp_path / "test.ldr"
        ldr.write_text(
            "0 Comment line\n"
            "1 15 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
            "1 4 20 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
            "1 1 0 -8 0 1 0 0 0 1 0 0 0 1 3004.dat\n"
        )
        result = _extract_parts_list(str(ldr))
        assert "3001.dat: 2" in result
        assert "3004.dat: 1" in result

    def test_empty_file_returns_no_parts_message(self, tmp_path: Path) -> None:
        ldr = tmp_path / "empty.ldr"
        ldr.write_text("")
        result = _extract_parts_list(str(ldr))
        assert "No parts found" in result

    def test_nonexistent_file_returns_error_message(self) -> None:
        result = _extract_parts_list("/nonexistent/path/does_not_exist.ldr")
        assert "not readable" in result.lower() or "LDR file" in result


# ---------------------------------------------------------------------------
# advisor_engine integration
# ---------------------------------------------------------------------------

FAKE_JSON = '{"score": 7, "confidence": 0.8, "findings": ["looks solid"]}'


class TestAdvisorEngineIntegration:
    def test_calls_all_nine_advisors_and_saves_report(self, tmp_path: Path) -> None:
        """advisor_engine must invoke subprocess.run 9 times (8 + warnings_judge) and write report."""
        iteration_dir = tmp_path / "iteration_1"
        iteration_dir.mkdir()

        fake_state: dict[str, Any] = {
            "suggestion_id": "aaaabbbb-cccc-dddd-eeee-ffffffffffff_0",
            "uuid_part": "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
            "ldr_path": str(tmp_path / "suggestion_0.ldr"),
            "preview_png_path": None,
            "pdf_path": str(tmp_path / "instructions.pdf"),
        }

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = FAKE_JSON
        mock_proc.stderr = ""

        patch_target = "tests.harness.advisor.subprocess.run"
        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake-token"}):
            with patch(patch_target, return_value=mock_proc) as mock_run:
                result = advisor_engine(
                    ADVISORS_YAML, GOLD_STEP_FINAL_PATH, iteration_dir, "test", fake_state,
                    scores_jsonl=tmp_path / "scores.jsonl",
                )

        assert mock_run.call_count == 9

        report_path = iteration_dir / "test_advisor_reports.json"
        assert report_path.exists(), "advisor_reports.json must be written"

        saved = json.loads(report_path.read_text())
        assert len(saved["scores_raw"]) == 9
        assert len(saved["scores_normalized"]) == 9
        assert len(saved["weights"]) == 9
        assert len(saved["advisors"]) == 9
        assert "warnings_judge" in saved["advisors"]
        assert "avg_normalized" in saved

        assert result["avg_normalized"] == saved["avg_normalized"]

    def test_all_timeouts_produce_score5_normalized_to_5(self, tmp_path: Path) -> None:
        """When all advisors time out, all raw scores=5 → std=0 → all normalized=5.0."""
        iteration_dir = tmp_path / "iteration_1"
        iteration_dir.mkdir()

        fake_state: dict[str, Any] = {
            "suggestion_id": "aaaa_0",
            "uuid_part": "aaaa",
            "ldr_path": str(tmp_path / "s.ldr"),
            "preview_png_path": None,
            "pdf_path": str(tmp_path / "ins.pdf"),
        }

        with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "fake-token"}):
            with patch(
                "tests.harness.advisor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=30),
            ):
                result = advisor_engine(
                    ADVISORS_YAML, GOLD_STEP_FINAL_PATH, iteration_dir, "test", fake_state,
                    scores_jsonl=tmp_path / "scores.jsonl",
                )

        assert math.isclose(result["avg_normalized"], 5.0), (
            f"Expected 5.0 but got {result['avg_normalized']}"
        )
        for aid, raw in result["scores_raw"].items():
            assert raw == 5, f"Advisor {aid} timed out but score={raw}, expected 5"

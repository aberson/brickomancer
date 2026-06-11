"""Tests for piece_detector and subprocess_utils.run_claude_subprocess.

All subprocess calls are mocked — no real claude CLI invocation.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from brickomancer.models.brick import PieceCount
from brickomancer.services.piece_detector import (
    _parse_pieces,
    _strip_markdown_fences,
    detect_pieces,
    merge_piece_lists,
)
from brickomancer.utils.subprocess_utils import run_claude_subprocess

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pc(part_id: str, qty: int, color: str) -> PieceCount:
    return PieceCount(part_id=part_id, qty=qty, color=color)


def _json_output(pieces: list[dict]) -> str:
    return json.dumps(pieces)


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------


class TestStripMarkdownFences:
    def test_no_fences(self):
        raw = '[{"part_id": "3001", "qty": 2, "color": "Red"}]'
        assert _strip_markdown_fences(raw) == raw.strip()

    def test_json_fence(self):
        raw = '```json\n[{"part_id": "3001", "qty": 2, "color": "Red"}]\n```'
        result = _strip_markdown_fences(raw)
        assert result == '[{"part_id": "3001", "qty": 2, "color": "Red"}]'

    def test_plain_fence(self):
        raw = '```\n[{"part_id": "3001", "qty": 1, "color": "Blue"}]\n```'
        result = _strip_markdown_fences(raw)
        assert result == '[{"part_id": "3001", "qty": 1, "color": "Blue"}]'

    def test_whitespace_trimmed(self):
        raw = "   []   "
        assert _strip_markdown_fences(raw) == "[]"


# ---------------------------------------------------------------------------
# _parse_pieces
# ---------------------------------------------------------------------------


class TestParsePieces:
    def test_valid_pieces(self):
        raw = _json_output([
            {"part_id": "3001", "qty": 4, "color": "Red"},
            {"part_id": "3004", "qty": 2, "color": "Blue"},
        ])
        result = _parse_pieces(raw)
        assert len(result) == 2
        assert result[0].part_id == "3001"
        assert result[0].qty == 4
        assert result[0].color == "Red"

    def test_invalid_part_id_filtered_out(self):
        """part_ids that are not 4-5 digits are filtered out."""
        raw = _json_output([
            {"part_id": "abc", "qty": 1, "color": "Red"},
            {"part_id": "99", "qty": 1, "color": "Blue"},
            {"part_id": "123456", "qty": 1, "color": "Green"},
            {"part_id": "3001", "qty": 2, "color": "White"},
        ])
        result = _parse_pieces(raw)
        assert len(result) == 1
        assert result[0].part_id == "3001"

    def test_5_digit_part_id_valid(self):
        """5-digit part_ids (like 60474) are accepted."""
        raw = _json_output([{"part_id": "60474", "qty": 1, "color": "Yellow"}])
        result = _parse_pieces(raw)
        assert len(result) == 1
        assert result[0].part_id == "60474"

    def test_zero_qty_filtered_out(self):
        raw = _json_output([{"part_id": "3001", "qty": 0, "color": "Red"}])
        result = _parse_pieces(raw)
        assert result == []

    def test_empty_color_filtered_out(self):
        raw = _json_output([{"part_id": "3001", "qty": 1, "color": ""}])
        result = _parse_pieces(raw)
        assert result == []

    def test_empty_list(self):
        result = _parse_pieces("[]")
        assert result == []

    def test_markdown_fences_stripped(self):
        raw = '```json\n[{"part_id": "3003", "qty": 3, "color": "Black"}]\n```'
        result = _parse_pieces(raw)
        assert len(result) == 1
        assert result[0].part_id == "3003"

    def test_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_pieces("not valid json")

    def test_non_list_json_raises_value_error(self):
        """JSON dict root (e.g. envelope from --output-format json) raises ValueError."""
        with pytest.raises(ValueError, match="Expected JSON list"):
            _parse_pieces('{"result": "...", "cost_usd": 0.01}')

    def test_returns_piece_count_instances(self):
        raw = _json_output([{"part_id": "3005", "qty": 10, "color": "Green"}])
        result = _parse_pieces(raw)
        assert all(isinstance(pc, PieceCount) for pc in result)


# ---------------------------------------------------------------------------
# merge_piece_lists
# ---------------------------------------------------------------------------


class TestMergePieceLists:
    def test_empty_input(self):
        assert merge_piece_lists([]) == []

    def test_single_list_passthrough(self):
        pieces = [_make_pc("3001", 4, "Red"), _make_pc("3004", 2, "Blue")]
        result = merge_piece_lists([pieces])
        # sorted by part_id: 3001, 3004
        assert result[0].part_id == "3001"
        assert result[1].part_id == "3004"

    def test_sums_duplicate_part_id_and_color(self):
        list1 = [_make_pc("3001", 4, "Red")]
        list2 = [_make_pc("3001", 6, "Red")]
        result = merge_piece_lists([list1, list2])
        assert len(result) == 1
        assert result[0].part_id == "3001"
        assert result[0].qty == 10
        assert result[0].color == "Red"

    def test_same_part_different_colors_kept_separate(self):
        list1 = [_make_pc("3001", 4, "Red")]
        list2 = [_make_pc("3001", 3, "Blue")]
        result = merge_piece_lists([list1, list2])
        assert len(result) == 2
        qtys = {pc.color: pc.qty for pc in result}
        assert qtys["Red"] == 4
        assert qtys["Blue"] == 3

    def test_sorted_by_part_id(self):
        list1 = [_make_pc("3010", 1, "White"), _make_pc("3001", 2, "White")]
        result = merge_piece_lists([list1])
        assert result[0].part_id == "3001"
        assert result[1].part_id == "3010"

    def test_multiple_lists_merged(self):
        list1 = [_make_pc("3001", 2, "Red"), _make_pc("3004", 1, "Blue")]
        list2 = [_make_pc("3001", 3, "Red"), _make_pc("3005", 5, "White")]
        list3 = [_make_pc("3004", 2, "Blue")]
        result = merge_piece_lists([list1, list2, list3])
        by_key = {(pc.part_id, pc.color): pc.qty for pc in result}
        assert by_key[("3001", "Red")] == 5
        assert by_key[("3004", "Blue")] == 3
        assert by_key[("3005", "White")] == 5

    def test_empty_sublists_handled(self):
        list1: list[PieceCount] = []
        list2 = [_make_pc("3001", 2, "Red")]
        result = merge_piece_lists([list1, list2])
        assert len(result) == 1
        assert result[0].qty == 2


# ---------------------------------------------------------------------------
# run_claude_subprocess (subprocess_utils)
# ---------------------------------------------------------------------------


class TestRunClaudeSubprocess:
    def test_raises_if_token_not_set(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="CLAUDE_CODE_OAUTH_TOKEN not set"):
            run_claude_subprocess("prompt", "image.jpg")

    def test_returns_stdout_on_success(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[{"part_id": "3001", "qty": 2, "color": "Red"}]'
        mock_result.stderr = ""

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result):
            output = run_claude_subprocess("my prompt", "image.jpg")

        assert output == '[{"part_id": "3001", "qty": 2, "color": "Red"}]'

    def test_raises_on_nonzero_exit(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "some error"

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="claude subprocess failed"):
                run_claude_subprocess("my prompt", "image.jpg")

    def test_token_passed_to_subprocess_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "my-secret-token")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        mock_result.stderr = ""

        with patch(
            "brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result
        ) as mock_run:
            run_claude_subprocess("prompt", "image.jpg")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "my-secret-token"

    def test_command_format(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        mock_result.stderr = ""

        with patch(
            "brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result
        ) as mock_run:
            run_claude_subprocess("my prompt", "/path/to/image.jpg")

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "claude"
        assert "--output-format" not in cmd
        assert "-p" in cmd
        assert "--image" in cmd
        assert "/path/to/image.jpg" in cmd
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"


# ---------------------------------------------------------------------------
# detect_pieces — integration with mocked subprocess
# ---------------------------------------------------------------------------


class TestDetectPieces:
    def _mock_subprocess(self, monkeypatch, output: str, token: str = "tok"):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = output
        mock_result.stderr = ""
        patcher = patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        )
        return patcher

    def test_single_image_returns_piece_counts(self, monkeypatch):
        payload = _json_output([
            {"part_id": "3001", "qty": 4, "color": "Red"},
            {"part_id": "3005", "qty": 2, "color": "White"},
        ])
        with self._mock_subprocess(monkeypatch, payload):
            result = detect_pieces(["image.jpg"])

        assert isinstance(result, list)
        assert all(isinstance(pc, PieceCount) for pc in result)
        by_id = {pc.part_id: pc for pc in result}
        assert "3001" in by_id
        assert by_id["3001"].qty == 4

    def test_valid_4_digit_part_id_present(self, monkeypatch):
        payload = _json_output([{"part_id": "3001", "qty": 1, "color": "Blue"}])
        with self._mock_subprocess(monkeypatch, payload):
            result = detect_pieces(["image.jpg"])
        assert len(result) == 1
        assert len(result[0].part_id) == 4
        assert result[0].part_id.isdigit()

    def test_multiple_images_merged(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        outputs = [
            _json_output([{"part_id": "3001", "qty": 2, "color": "Red"}]),
            _json_output([{"part_id": "3001", "qty": 3, "color": "Red"}]),
        ]
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            r = MagicMock()
            r.returncode = 0
            r.stdout = outputs[call_count]
            r.stderr = ""
            call_count += 1
            return r

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", side_effect=fake_run):
            result = detect_pieces(["img1.jpg", "img2.jpg"])

        assert len(result) == 1
        assert result[0].part_id == "3001"
        assert result[0].qty == 5

    def test_json_parse_failure_returns_empty_gracefully(self, monkeypatch):
        """If Claude returns invalid JSON all retries, detect_pieces returns []."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json at all"
        mock_result.stderr = ""

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result):
            result = detect_pieces(["image.jpg"])

        assert result == []

    def test_subprocess_runtime_error_returns_empty(self, monkeypatch):
        """If subprocess raises RuntimeError, detect_pieces returns empty gracefully."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "auth failure"

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", return_value=mock_result):
            result = detect_pieces(["image.jpg"])

        assert result == []

    def test_empty_image_list(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        result = detect_pieces([])
        assert result == []

    def test_result_sorted_by_part_id(self, monkeypatch):
        payload = _json_output([
            {"part_id": "3010", "qty": 1, "color": "White"},
            {"part_id": "3001", "qty": 2, "color": "Red"},
        ])
        with self._mock_subprocess(monkeypatch, payload):
            result = detect_pieces(["image.jpg"])

        assert result[0].part_id == "3001"
        assert result[1].part_id == "3010"

    def test_retry_on_json_parse_failure(self, monkeypatch):
        """First call returns bad JSON; second returns valid JSON — should succeed."""
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        outputs = [
            "bad json",
            _json_output([{"part_id": "3001", "qty": 1, "color": "Red"}]),
        ]
        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            r = MagicMock()
            r.returncode = 0
            r.stdout = outputs[min(call_count, len(outputs) - 1)]
            r.stderr = ""
            call_count += 1
            return r

        with patch("brickomancer.utils.subprocess_utils.subprocess.run", side_effect=fake_run):
            result = detect_pieces(["image.jpg"])

        assert len(result) == 1
        assert result[0].part_id == "3001"

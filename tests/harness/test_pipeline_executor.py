"""Unit tests for pipeline_executor in run_harness.py.

All HTTP calls and real filesystem state are mocked; only temp dirs are used.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from tests.harness.run_harness import pipeline_executor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Real image used as input fixture — content doesn't matter for these tests
# (all HTTP is mocked); file just needs to be openable.
_INPUT_IMAGE = (
    Path(__file__).parents[2]
    / "docs"
    / "example_input_output"
    / "star"
    / "input_image"
    / "cartoon_star.jpg"
)

UUID_PART = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
SUGGESTION_ID = f"{UUID_PART}_0"
FAKE_PDF = b"%PDF-1.4 fake"


def _make_generate_response(suggestions: list[dict]) -> MagicMock:
    """Return a mock httpx.Response for /from-image."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"suggestions": suggestions}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_instructions_response(pdf_bytes: bytes = FAKE_PDF) -> MagicMock:
    """Return a mock httpx.Response for /instructions."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.content = pdf_bytes
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _three_suggestions() -> list[dict]:
    return [
        {
            "id": f"{UUID_PART}_0",
            "tier": "compact",
            "preview_url": "/tmp/preview_0.png",
            "parts_count": 12,
            "parts_list": [],
        },
        {
            "id": f"{UUID_PART}_1",
            "tier": "standard",
            "preview_url": "/tmp/preview_1.png",
            "parts_count": 30,
            "parts_list": [],
        },
        {
            "id": f"{UUID_PART}_2",
            "tier": "detailed",
            "preview_url": "/tmp/preview_2.png",
            "parts_count": 75,
            "parts_list": [],
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineExecutorHappyPath:
    """Happy path: 3 suggestions, compact selected, PDF saved."""

    def test_returns_expected_keys(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            result = pipeline_executor(tmp_path, _INPUT_IMAGE)

        assert set(result.keys()) == {
            "suggestion_id",
            "uuid_part",
            "ldr_path",
            "preview_png_path",
            "pdf_path",
            "input_image_path",
        }

    def test_pdf_is_saved_to_iteration_dir(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            result = pipeline_executor(tmp_path, _INPUT_IMAGE)

        pdf_path = Path(result["pdf_path"])
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == FAKE_PDF

    def test_suggestion_id_is_compact(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            result = pipeline_executor(tmp_path, _INPUT_IMAGE)

        assert result["suggestion_id"] == SUGGESTION_ID
        assert result["uuid_part"] == UUID_PART

    def test_ldr_path_uses_uuid_part(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            result = pipeline_executor(tmp_path, _INPUT_IMAGE)

        assert UUID_PART in result["ldr_path"]
        assert result["ldr_path"].endswith("suggestion_0.ldr")

    def test_preview_copied_when_present(self, tmp_path: Path) -> None:
        """When the preview PNG exists in TMP_DIR_PATH, it should be copied."""
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        # Create a fake preview PNG in a fake TMP_DIR_PATH
        fake_tmp = tmp_path / "tmp_root"
        fake_preview_dir = fake_tmp / UUID_PART
        fake_preview_dir.mkdir(parents=True)
        fake_preview = fake_preview_dir / "suggestion_0_preview.png"
        fake_preview.write_bytes(b"\x89PNG fake")

        iteration_out = tmp_path / "iteration_1"
        iteration_out.mkdir()

        with (
            patch("tests.harness.run_harness.httpx.Client", return_value=mock_client),
            patch("tests.harness.run_harness.TMP_DIR_PATH", fake_tmp),
        ):
            result = pipeline_executor(iteration_out, _INPUT_IMAGE)

        copied = iteration_out / "preview.png"
        assert copied.exists()
        assert copied.read_bytes() == b"\x89PNG fake"
        assert result["preview_png_path"] == str(copied)


class TestPipelineExecutorNoCompact:
    """No compact suggestion → ValueError."""

    def test_raises_value_error(self, tmp_path: Path) -> None:
        suggestions_no_compact = [
            {
                "id": f"{UUID_PART}_1",
                "tier": "standard",
                "preview_url": "",
                "parts_count": 30,
                "parts_list": [],
            },
        ]
        gen_resp = _make_generate_response(suggestions_no_compact)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = gen_resp

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="No compact suggestion"):
                pipeline_executor(tmp_path, _INPUT_IMAGE)

    def test_raises_when_suggestions_empty(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response([])

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = gen_resp

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="No compact suggestion"):
                pipeline_executor(tmp_path, _INPUT_IMAGE)


class TestPipelineExecutorHTTPErrors:
    """HTTP errors from /from-image propagate out of pipeline_executor."""

    def test_http_status_error_propagates(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        gen_resp = MagicMock(spec=httpx.Response)
        gen_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(),
        )
        mock_client.post.return_value = gen_resp

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                pipeline_executor(tmp_path, _INPUT_IMAGE)

    def test_timeout_exception_propagates(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timed out")

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(httpx.TimeoutException):
                pipeline_executor(tmp_path, _INPUT_IMAGE)

    def test_http_error_on_instructions_call(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [
            gen_resp,
            httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock()),
        ]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                pipeline_executor(tmp_path, _INPUT_IMAGE)


class TestPipelineExecutorMissingPreview:
    """Missing preview PNG → no exception, warning logged."""

    def test_no_exception_when_preview_missing(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        # Point TMP_DIR_PATH at an empty directory so preview is missing
        fake_tmp = tmp_path / "empty_tmp"
        fake_tmp.mkdir()

        iteration_out = tmp_path / "iteration_1"
        iteration_out.mkdir()

        with (
            patch("tests.harness.run_harness.httpx.Client", return_value=mock_client),
            patch("tests.harness.run_harness.TMP_DIR_PATH", fake_tmp),
        ):
            # Must not raise
            result = pipeline_executor(iteration_out, _INPUT_IMAGE)

        # PDF should still be saved
        assert Path(result["pdf_path"]).exists()
        # preview.png should NOT exist in the output dir
        assert not (iteration_out / "preview.png").exists()
        # preview_png_path should be None, not a non-existent source path
        assert result["preview_png_path"] is None

    def test_warning_logged_when_preview_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(FAKE_PDF)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        fake_tmp = tmp_path / "empty_tmp"
        fake_tmp.mkdir()

        iteration_out = tmp_path / "iteration_1"
        iteration_out.mkdir()

        with (
            patch("tests.harness.run_harness.httpx.Client", return_value=mock_client),
            patch("tests.harness.run_harness.TMP_DIR_PATH", fake_tmp),
            caplog.at_level(logging.WARNING, logger="harness"),
        ):
            pipeline_executor(iteration_out, _INPUT_IMAGE)

        assert len(caplog.records) >= 1
        assert any("Preview PNG not found" in rec.message for rec in caplog.records)


class TestPipelineExecutorEmptyPDF:
    """Empty PDF bytes from /instructions → ValueError."""

    def test_raises_on_empty_pdf_bytes(self, tmp_path: Path) -> None:
        gen_resp = _make_generate_response(_three_suggestions())
        instr_resp = _make_instructions_response(b"")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [gen_resp, instr_resp]

        with patch("tests.harness.run_harness.httpx.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="empty PDF bytes"):
                pipeline_executor(tmp_path, _INPUT_IMAGE)

"""Tests for instruction_service.generate_pdf and subprocess_utils.run_lpub3d.

All subprocess and shutil.which calls are mocked — no real LPub3D invocation.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from brickomancer.services.instruction_service import (
    ToolUnavailableError,
    generate_pdf,
)
from brickomancer.utils.subprocess_utils import run_lpub3d

# ---------------------------------------------------------------------------
# instruction_service.generate_pdf
# ---------------------------------------------------------------------------


class TestGeneratePdf:
    def test_returns_pdf_path(self, tmp_path):
        """generate_pdf returns the path returned by run_lpub3d."""
        expected = str(tmp_path / "model.pdf")

        with patch(
            "brickomancer.services.instruction_service.run_lpub3d",
            return_value=expected,
        ):
            result = generate_pdf("model.ldr", str(tmp_path))

        assert result == expected
        assert result.endswith(".pdf")

    def test_tool_unavailable_error_raised_when_not_on_path(self, tmp_path):
        """RuntimeError 'LPub3D not found on PATH' is converted to ToolUnavailableError."""
        with patch(
            "brickomancer.services.instruction_service.run_lpub3d",
            side_effect=RuntimeError("LPub3D not found on PATH"),
        ):
            with pytest.raises(ToolUnavailableError):
                generate_pdf("model.ldr", str(tmp_path))

    def test_other_runtime_error_propagates_unchanged(self, tmp_path):
        """RuntimeErrors unrelated to PATH availability propagate as RuntimeError."""
        with patch(
            "brickomancer.services.instruction_service.run_lpub3d",
            side_effect=RuntimeError("LPub3D failed: some render error"),
        ):
            with pytest.raises(RuntimeError, match="LPub3D failed: some render error"):
                generate_pdf("model.ldr", str(tmp_path))

    def test_other_runtime_error_not_tool_unavailable(self, tmp_path):
        """Other RuntimeErrors must NOT be wrapped as ToolUnavailableError."""
        with patch(
            "brickomancer.services.instruction_service.run_lpub3d",
            side_effect=RuntimeError("LPub3D failed: out of memory"),
        ):
            with pytest.raises(RuntimeError):
                try:
                    generate_pdf("model.ldr", str(tmp_path))
                except ToolUnavailableError:
                    pytest.fail("ToolUnavailableError raised for non-PATH error")


# ---------------------------------------------------------------------------
# subprocess_utils.run_lpub3d
# ---------------------------------------------------------------------------


class TestRunLpub3d:
    def _make_mock_run(self, returncode: int = 0, stderr: str = "") -> MagicMock:
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = ""
        mock_result.stderr = stderr
        return mock_result

    def test_returns_pdf_path_on_success(self, tmp_path):
        """When lpub3d exits 0 and a .pdf exists, return its path."""
        pdf_file = tmp_path / "model.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        mock_result = self._make_mock_run(returncode=0)

        with patch("shutil.which", return_value="lpub3d"), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        ):
            result = run_lpub3d("model.ldr", str(tmp_path))

        assert result.endswith(".pdf")
        assert os.path.basename(result) == "model.pdf"

    def test_raises_runtime_error_on_nonzero_exit(self, tmp_path):
        """Non-zero return code raises RuntimeError containing stderr."""
        mock_result = self._make_mock_run(returncode=1, stderr="segmentation fault")

        with patch("shutil.which", return_value="lpub3d"), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        ):
            with pytest.raises(RuntimeError, match="LPub3D failed"):
                run_lpub3d("model.ldr", str(tmp_path))

    def test_raises_runtime_error_when_no_pdf_produced(self, tmp_path):
        """Exit 0 but no .pdf in output_dir raises RuntimeError."""
        mock_result = self._make_mock_run(returncode=0)

        with patch("shutil.which", return_value="lpub3d"), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        ):
            with pytest.raises(RuntimeError, match="no .pdf found"):
                run_lpub3d("model.ldr", str(tmp_path))

    def test_raises_runtime_error_when_lpub3d_not_on_path(self, tmp_path):
        """shutil.which returning None for all candidates raises RuntimeError."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="LPub3D not found on PATH"):
                run_lpub3d("model.ldr", str(tmp_path))

    def test_uses_lpub3d_exe_fallback(self, tmp_path):
        """Falls back to 'lpub3d.exe' when 'lpub3d' is not found."""
        pdf_file = tmp_path / "out.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        mock_result = self._make_mock_run(returncode=0)

        def which_side_effect(name: str) -> str | None:
            return "lpub3d.exe" if name == "lpub3d.exe" else None

        with patch("shutil.which", side_effect=which_side_effect), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            result = run_lpub3d("model.ldr", str(tmp_path))

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "lpub3d.exe"
        assert result.endswith(".pdf")

    def test_run_lpub3d_raises_on_timeout(self, tmp_path):
        """subprocess.TimeoutExpired is caught and re-raised as RuntimeError with 'timed out'."""
        with patch("shutil.which", return_value="lpub3d"), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=120),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                run_lpub3d("model.ldr", str(tmp_path))

    def test_command_format(self, tmp_path):
        """Verify the subprocess is called with the correct argument order."""
        pdf_file = tmp_path / "model.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        mock_result = self._make_mock_run(returncode=0)

        with patch("shutil.which", return_value="lpub3d"), patch(
            "brickomancer.utils.subprocess_utils.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            run_lpub3d("/path/to/model.ldr", str(tmp_path))

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "lpub3d"
        assert "-pdf" in cmd
        assert "-o" in cmd
        o_idx = cmd.index("-o")
        assert cmd[o_idx + 1] == str(tmp_path)
        assert cmd[-1] == "/path/to/model.ldr"

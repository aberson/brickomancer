"""Subprocess utilities for calling external tools (Claude CLI, LDView, LPub3D)."""

import glob
import os
import shutil
import subprocess
from pathlib import Path

_LPUB3D_NOT_FOUND_MSG = "LPub3D not found on PATH"


def run_claude_subprocess(prompt: str, image_path: str) -> str:
    """Call the Claude CLI subprocess for piece detection.

    Reads CLAUDE_CODE_OAUTH_TOKEN from the environment (loaded from .env at
    startup by python-dotenv in main.py).

    Args:
        prompt: The prompt text to send to Claude.
        image_path: Path to the image file to analyze.

    Returns:
        Raw string output from Claude (expected to be JSON).

    Raises:
        RuntimeError: If CLAUDE_CODE_OAUTH_TOKEN is not set.
        RuntimeError: If the subprocess exits with a non-zero return code.
    """
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set")

    cmd = ["claude", "-p", prompt, "--image", image_path]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token},
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude subprocess failed: {result.stderr}")
    return result.stdout


def run_ldview(ldr_path: str, output_png: str) -> None:
    """Call LDView headless to render an LDraw file to a PNG.

    Args:
        ldr_path: Path to the .ldr input file.
        output_png: Path where the output PNG should be written.

    Raises:
        RuntimeError: If LDView is not found on PATH or the render fails.
    """
    ldview_cmd: str | None = None
    for cmd_name in ("ldview", "LDView", "ldview.exe"):
        if shutil.which(cmd_name):
            ldview_cmd = cmd_name
            break
    if ldview_cmd is None:
        raise RuntimeError("LDView not found on PATH")

    result = subprocess.run(
        [
            ldview_cmd,
            ldr_path,
            f"-SaveSnapshot={output_png}",
            "-ExportFile=1",
            "-SaveWidth=400",
            "-SaveHeight=300",
            "-AutoCrop=1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LDView failed: {result.stderr}")
    if not Path(output_png).exists():
        raise RuntimeError(f"LDView exited 0 but did not write {output_png}")


def run_lpub3d(ldr_path: str, output_dir: str) -> str:
    """Call LPub3D headless to generate a PDF instruction book.

    Args:
        ldr_path: Path to the .ldr input file.
        output_dir: Directory where the output PDF should be written.

    Returns:
        Path to the generated PDF file.

    Raises:
        RuntimeError: If LPub3D is not found on PATH, the render fails,
            or no PDF is produced.
    """
    lpub3d_cmd: str | None = None
    for cmd_name in ("lpub3d", "lpub3d.exe"):
        if shutil.which(cmd_name):
            lpub3d_cmd = cmd_name
            break
    if lpub3d_cmd is None:
        raise RuntimeError(_LPUB3D_NOT_FOUND_MSG)

    try:
        result = subprocess.run(
            [lpub3d_cmd, "-pdf", "-o", output_dir, ldr_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("LPub3D timed out after 120s") from exc
    if result.returncode != 0:
        raise RuntimeError(f"LPub3D failed: {result.stderr}")

    pdfs = glob.glob(os.path.join(output_dir, "*.pdf"))
    if not pdfs:
        raise RuntimeError(f"LPub3D exited 0 but no .pdf found in {output_dir}")
    return pdfs[0]

"""Subprocess utilities for calling external tools (Claude CLI, LDView, LPub3D)."""

import os
import subprocess


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
        RuntimeError: If LDView is not found or the render fails.
    """
    # Implemented in Step 8
    raise NotImplementedError("run_ldview not yet implemented (Step 8)")


def run_lpub3d(ldr_path: str, output_dir: str) -> str:
    """Call LPub3D headless to generate a PDF instruction book.

    Args:
        ldr_path: Path to the .ldr input file.
        output_dir: Directory where the output PDF should be written.

    Returns:
        Path to the generated PDF file.

    Raises:
        RuntimeError: If LPub3D is not found or PDF generation fails.
    """
    # Implemented in Step 9
    raise NotImplementedError("run_lpub3d not yet implemented (Step 9)")

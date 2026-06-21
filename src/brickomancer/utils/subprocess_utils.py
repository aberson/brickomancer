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

    full_prompt = (
        f"{prompt}\n\nThe image to analyze is at this absolute path: {image_path}\n"
        "Use your Read tool to view this image."
    )
    cmd = ["claude", "-p", full_prompt]
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


def run_claude_text(prompt: str) -> str:
    """Call the Claude CLI subprocess with a text-only prompt (no image).

    The text-path counterpart of :func:`run_claude_subprocess`: no ``--image``,
    no embedded image path. Used by ``TextShaper`` to get a sparse voxel
    occupancy from a text description. Reads ``CLAUDE_CODE_OAUTH_TOKEN`` from the
    environment (never ``ANTHROPIC_API_KEY``).

    Args:
        prompt: The full prompt text to send to Claude.

    Returns:
        Raw string output from Claude (expected to be JSON).

    Raises:
        RuntimeError: If ``CLAUDE_CODE_OAUTH_TOKEN`` is not set, or the
            subprocess exits with a non-zero return code.
    """
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set")

    cmd = ["claude", "-p", prompt]
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


# LPub3D ships its own LDView binary pre-configured with the parts library.
# Prefer it over the standalone LDView install, which has no bundled parts.
_LPUB3D_LDVIEW_CANDIDATES: list[str] = [
    r"C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe",
    r"C:\Program Files\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe",
    r"C:\Program Files (x86)\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe",
]
# LPub3D also ships its own LDraw parts library â€” pass it to standalone LDView.
_LPUB3D_LDRAW_CANDIDATES: list[str] = [
    r"C:\Tools\LPub3D\ldraw",
    r"C:\Program Files\LPub3D\ldraw",
    r"C:\Program Files (x86)\LPub3D\ldraw",
]


def _find_ldraw_dir() -> str | None:
    """Return the first LDraw parts directory found from LPub3D installs."""
    for d in _LPUB3D_LDRAW_CANDIDATES:
        if Path(d).is_dir():
            return d
    return None


def run_ldview(ldr_path: str, output_png: str) -> None:
    """Call LDView headless to render an LDraw file to a PNG.

    Args:
        ldr_path: Path to the .ldr input file.
        output_png: Path where the output PNG should be written.

    Raises:
        RuntimeError: If LDView is not found or the render fails.
    """
    # Prefer LPub3D's bundled LDView (pre-configured with parts library).
    ldview_cmd: str | None = None
    for path in _LPUB3D_LDVIEW_CANDIDATES:
        if Path(path).exists():
            ldview_cmd = path
            break
    if ldview_cmd is None:
        for cmd_name in ("LDView64", "LDView64.exe", "ldview", "LDView", "ldview.exe"):
            found = shutil.which(cmd_name)
            if found:
                ldview_cmd = found
                break
    if ldview_cmd is None:
        raise RuntimeError("LDView not found on PATH")

    cmd: list[str] = [
        ldview_cmd,
        ldr_path,
        f"-SaveSnapshot={output_png}",
        "-ExportFile=1",
        "-SaveWidth=800",
        "-SaveHeight=600",
        "-AutoCrop=1",
        "-Latitude=35",
        "-Longitude=45",
    ]
    # Always pass the LDraw library dir â€” even LPub3D's bundled LDView needs it
    # when invoked as a standalone subprocess (it doesn't auto-detect its own parts dir).
    ldraw_dir = _find_ldraw_dir()
    if ldraw_dir:
        cmd.append(f"-LDrawDir={ldraw_dir}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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
    for cmd_name in ("LPub3D", "LPub3D.exe", "lpub3d", "lpub3d.exe"):
        found = shutil.which(cmd_name)
        if found:
            lpub3d_cmd = found
            break
    if lpub3d_cmd is None:
        raise RuntimeError(_LPUB3D_NOT_FOUND_MSG)

    # LPub3D writes the PDF next to the input .ldr file as <basename>_<dpi>_DPI.pdf.
    # The -x flag activates headless export mode; -pe pdf selects PDF output.
    # Run from LPub3D's own install dir so it auto-detects its bundled LDraw library;
    # pass an absolute ldr_path so the PDF is written next to the source file regardless of cwd.
    abs_ldr_path = os.path.abspath(ldr_path)
    ldr_dir = os.path.dirname(abs_ldr_path)
    lpub3d_dir = os.path.dirname(os.path.abspath(lpub3d_cmd))
    try:
        result = subprocess.run(
            [lpub3d_cmd, "-x", "-pe", "pdf", abs_ldr_path],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=lpub3d_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("LPub3D timed out after 120s") from exc
    if result.returncode != 0:
        raise RuntimeError(f"LPub3D failed: {result.stderr}")

    pdfs = glob.glob(os.path.join(ldr_dir, "*.pdf"))
    if not pdfs:
        raise RuntimeError(f"LPub3D exited 0 but no .pdf found in {ldr_dir}")
    return pdfs[0]

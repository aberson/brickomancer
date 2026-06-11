"""Instruction service — generates PDF instruction books via LPub3D."""


from brickomancer.utils.subprocess_utils import _LPUB3D_NOT_FOUND_MSG, run_lpub3d


class ToolUnavailableError(Exception):
    """Raised when a required external tool is not installed or not on PATH."""


def generate_pdf(ldr_path: str, output_dir: str) -> str:
    """Generate a step-by-step instruction PDF from an LDraw file.

    Args:
        ldr_path: Path to the .ldr input file.
        output_dir: Directory where the output PDF should be written.

    Returns:
        Path to the generated PDF file.

    Raises:
        ToolUnavailableError: If LPub3D is not on PATH.
        RuntimeError: If LPub3D fails for any other reason.
    """
    try:
        return run_lpub3d(ldr_path, output_dir)
    except RuntimeError as exc:
        if _LPUB3D_NOT_FOUND_MSG in str(exc):
            raise ToolUnavailableError(str(exc)) from exc
        raise

"""Instruction service — generates PDF instruction books via LPub3D.

Implemented in Step 9.
"""


def generate_pdf(ldr_path: str, output_dir: str) -> str:  # type: ignore[empty-body]
    """Generate a step-by-step instruction PDF from an LDraw file.

    Args:
        ldr_path: Path to the .ldr input file.
        output_dir: Directory where the output PDF should be written.

    Returns:
        Path to the generated PDF file.

    Raises:
        ToolUnavailableError: If LPub3D is not on PATH.
    """
    ...

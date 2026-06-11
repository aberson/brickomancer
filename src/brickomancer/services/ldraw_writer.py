"""LDraw writer — converts BrickPlacements to .ldr file format.

Implemented in Step 6.
"""


def write_ldr(placements: list, output_path: str, tier_name: str) -> str:  # type: ignore[empty-body]
    """Write a list of BrickPlacements to an LDraw .ldr file.

    Args:
        placements: list[BrickPlacement] to write.
        output_path: Path where the .ldr file should be written.
        tier_name: Tier label for the file header (e.g. "compact").

    Returns:
        Path to the written .ldr file.
    """
    ...


def sequence_steps(placements: list, bricks_per_step: int = 8) -> list:  # type: ignore[empty-body]
    """Group BrickPlacements into build steps (Y-sorted, batches of bricks_per_step).

    Args:
        placements: list[BrickPlacement] to sequence.
        bricks_per_step: Number of bricks per step group (default 8).

    Returns:
        list[list[BrickPlacement]] — one sublist per build step.
    """
    ...

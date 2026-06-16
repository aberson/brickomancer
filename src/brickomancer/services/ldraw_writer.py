"""LDraw writer — converts BrickPlacements to .ldr file format.

Public API
----------
write_ldr(placements, output_path, tier_name) -> str
    Write a sorted, step-sequenced LDraw .ldr file.

sequence_steps(placements, bricks_per_step) -> list[list[BrickPlacement]]
    Group placements into build steps (one step per Y-layer, batched by
    bricks_per_step within each layer).

LDraw coordinate system
-----------------------
  1 stud = 20 LDU in X and Z.
  1 layer = 24 LDU in Y (Y increases downward in LDraw).
  Voxel (sx, sy, sz) maps to LDraw (sx*20, sy*-24, sz*20) so that the
  bottom of the build (sy=0) sits at LDraw y=0 and higher layers have
  more-negative Y values.

  Tiles are 8 LDU tall (vs 24 LDU for standard bricks). A tile at voxel
  layer y sits on the studs of the bricks at layer y-1, so its LDraw Y
  is (y-1)*-24 - 8 = y*-24 + 16. Standard brick formula is unchanged.

Line format:
  1 <color_id> <x> <y> <z> 1 0 0 0 1 0 0 0 1 <part_file>.dat

Step markers:
  ``0 STEP`` is inserted after every non-empty step including the last, so
  LPub3D renders each step as a separate page.  ``0 !LPUB INSERT BOM`` is
  placed immediately after the final ``0 STEP`` so LPub3D renders a
  consolidated parts-inventory page.
"""

import os
from itertools import groupby

from brickomancer.models.brick import TILE_PART_IDS, BrickPlacement

# LDraw unit conversion constants
_STUD_LDU = 20   # 1 stud = 20 LDU in X and Z
_LAYER_LDU = 24  # 1 layer = 24 LDU in Y
_TILE_HEIGHT_LDU = 8  # tiles are 8 LDU tall (same as a plate)

_TILE_PART_ID_SET: frozenset[str] = frozenset(TILE_PART_IDS.values())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_ldu(bp: BrickPlacement) -> tuple[int, int, int]:
    """Convert stud coordinates to LDraw units."""
    x = bp.x * _STUD_LDU + (bp.width - 1) * 10
    if bp.part_id in _TILE_PART_ID_SET:
        # Tiles are 8 LDU tall; they sit on the studs of the layer below.
        # Correct Y = (y-1)*-24 - 8 = y*-24 + 16
        y = bp.y * -_LAYER_LDU + (_LAYER_LDU - _TILE_HEIGHT_LDU)
    else:
        y = bp.y * -_LAYER_LDU  # negate: voxel y-up -> LDraw y-down
    z = bp.z * _STUD_LDU + (bp.length - 1) * 10
    return x, y, z


def _brick_line(bp: BrickPlacement) -> str:
    """Return the LDraw ``1 ...`` line for a single brick."""
    x, y, z = _to_ldu(bp)
    return f"1 {bp.color_id} {x} {y} {z} 1 0 0 0 1 0 0 0 1 {bp.part_id}.dat"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sequence_steps(
    placements: list[BrickPlacement],
    bricks_per_step: int = 8,
) -> list[list[BrickPlacement]]:
    """Group BrickPlacements into build steps by Y-layer, then by bricks_per_step.

    Each distinct voxel Y-layer becomes at least one build step, preserving
    the vertical stacking sequence.  Large layers are split into sub-steps of
    bricks_per_step bricks each.

    Args:
        placements: list[BrickPlacement] to sequence.
        bricks_per_step: Max bricks per step within a single layer (default 8).

    Returns:
        list[list[BrickPlacement]] -- one sublist per build step.
    """
    sorted_bricks = sorted(placements, key=lambda bp: (bp.y, bp.x, bp.z))
    steps: list[list[BrickPlacement]] = []
    for _, layer_iter in groupby(sorted_bricks, key=lambda bp: bp.y):
        layer_bricks = list(layer_iter)
        for i in range(0, len(layer_bricks), bricks_per_step):
            steps.append(layer_bricks[i : i + bricks_per_step])
    return steps


def write_ldr(
    placements: list[BrickPlacement],
    output_path: str,
    tier_name: str = "build",
) -> str:
    """Write a list of BrickPlacements to an LDraw .ldr file.

    Bricks are grouped by Y-layer (ascending voxel layer) so each layer
    is a distinct build step.  Large layers are split into sub-steps of 8.
    A ``0 STEP`` marker is inserted after every non-empty step, including
    the last, so LPub3D renders each step as a separate page.  Empty steps
    are skipped entirely to prevent LPub3D from rendering a blank page 1.

    LPub3D meta commands emitted:
    - Immediately after final ``0 STEP``: ``0 !LPUB INSERT BOM``.

    Args:
        placements: list[BrickPlacement] to write.
        output_path: Path where the .ldr file should be written.
        tier_name: Tier label for the file header (e.g. "compact").

    Returns:
        The absolute path to the written .ldr file.
    """
    filename = os.path.basename(output_path)
    steps = sequence_steps(placements)

    lines: list[str] = [
        "0 Brickomancer Build",
        f"0 Name: {filename}",
        "0 Author: Brickomancer",
        f"0 Tier: {tier_name}",
        "",
        "0 STEP",  # cover page step
    ]

    for step_bricks in steps:
        if not step_bricks:
            continue
        for bp in step_bricks:
            lines.append(_brick_line(bp))
        lines.append("0 STEP")

    lines.append("0 !LPUB INSERT BOM")

    parent = os.path.dirname(os.path.abspath(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    return os.path.abspath(output_path)

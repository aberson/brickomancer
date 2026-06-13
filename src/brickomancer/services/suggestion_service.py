"""Suggestion service â€” generates 3 LEGO build suggestions from a voxel grid.

Public API
----------
generate_suggestions(grid, colors, tmp_dir, request_id, piece_inventory) -> list[Suggestion]
    Produces compact, standard, and detailed tier suggestions.  For each tier:
      1. Optionally downsample the voxel grid (compact tier only).
      2. Call brick_packer.pack() with the dominant color.
      3. Write an LDraw .ldr file via ldraw_writer.write_ldr().
      4. Render a preview PNG via subprocess_utils.run_ldview().
      5. Build a parts list from the placements.

Tier definitions
----------------
  0 â€” compact  : every-other-stud downsample (step=2 on X and Z axes),
                 full brick-type set.
  1 â€” standard : original grid, full brick-type set.
  2 â€” detailed : original grid, only 1Ã—2 and 1Ã—1 bricks for finer grain.

Color assignment
----------------
The dominant ColorMatch drives all tiers. Background colors (low saturation,
high lightness) are skipped so the subject color is used instead of the
background. Falls back to colors[0] if no subject color is found.
Its color_id is passed to pack(); its name/hex are used in the parts list.
"""

from collections import defaultdict
from pathlib import Path

import numpy as np

from brickomancer.models.brick import ColorMatch, PieceCount
from brickomancer.models.schemas import PartCount, Suggestion
from brickomancer.services import brick_packer, data_service, ldraw_writer
from brickomancer.utils.subprocess_utils import run_ldview

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

_TIERS: list[tuple[str, bool, list[tuple[int, int]] | None]] = [
    # (tier_name, downsample, brick_set_override)
    ("compact", True, None),
    ("standard", False, None),
    ("detailed", False, [(1, 2), (1, 1)]),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _downsample(grid: np.ndarray) -> np.ndarray:
    """Keep every other stud on X and Z (step=2), preserving all Y layers."""
    return grid[::2, :, ::2]


def _select_subject_color(colors: list[ColorMatch]) -> ColorMatch:
    """Return the first non-background color from the sorted color list.

    Background colors (near-white, near-gray) have low HSV saturation and
    high lightness. We skip them to avoid using the image background as the
    build color instead of the actual subject.
    """
    for c in colors:
        h = c.hex.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        saturation = (max_c - min_c) / max_c if max_c > 0 else 0.0
        lightness = (max_c + min_c) / 510.0
        if saturation > 0.15 or lightness < 0.35:
            return c
    return colors[0]


def _build_parts_list(placements: list) -> list[PartCount]:
    """Group BrickPlacements by (part_id, color_id) and build PartCount objects.

    Color name and hex are resolved from data_service.get_color().
    Falls back to empty strings when the color_id is not in any data file.
    """
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for bp in placements:
        counts[(bp.part_id, bp.color_id)] += 1

    result: list[PartCount] = []
    for (part_id, color_id), qty in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        color_entry = data_service.get_color(color_id)
        if color_entry is not None:
            color_name = color_entry.get("name", "")
            color_hex = "#" + color_entry.get("hex", "000000").lstrip("#")
        else:
            color_name = str(color_id)
            color_hex = "#000000"
        result.append(
            PartCount(
                part_id=part_id,
                color_name=color_name,
                color_hex=color_hex,
                qty=qty,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_suggestions(
    grid: np.ndarray,
    colors: list[ColorMatch],
    tmp_dir: Path | str,
    request_id: str,
    piece_inventory: list[PieceCount] | None = None,
) -> list[Suggestion]:
    """Generate compact, standard, and detailed LEGO build suggestions.

    Args:
        grid: numpy.ndarray[bool] of shape (X, Y, Z) â€” voxel occupancy.
        colors: list[ColorMatch] sorted by cluster_weight descending (dominant first).
        tmp_dir: Directory path for writing .ldr and .png scratch files.
        request_id: UUID string used as a prefix for suggestion IDs and filenames.
        piece_inventory: Optional list[PieceCount] (reserved for future soft
            constraint; not yet applied).

    Returns:
        list[Suggestion] with exactly 3 items in order: compact, standard, detailed.

    Raises:
        ValueError: If *colors* is empty.
        RuntimeError: If LDView is not on PATH (propagated from run_ldview).
    """
    if not colors:
        raise ValueError("colors must be non-empty")

    dominant = _select_subject_color(colors)
    tmp_path = Path(tmp_dir)
    tmp_path.mkdir(parents=True, exist_ok=True)

    suggestions: list[Suggestion] = []

    for tier_index, (tier_name, downsample, brick_set_override) in enumerate(_TIERS):
        suggestion_id = f"{request_id}_{tier_index}"

        # --- 1. Prepare grid -------------------------------------------------
        working_grid = _downsample(grid) if downsample else grid

        # Guard: empty grid after downsampling still needs at least one voxel
        # so the packer doesn't crash.  The packer handles all-False grids
        # gracefully (returns []), so no special handling needed here.

        # --- 2. Pack bricks --------------------------------------------------
        placements = brick_packer.pack(
            working_grid,
            color_id=dominant.color_id,
            brick_set=brick_set_override,
        )

        # --- 3. Write LDraw file ---------------------------------------------
        ldr_filename = f"suggestion_{tier_index}.ldr"
        ldr_path = str(tmp_path / ldr_filename)
        ldraw_writer.write_ldr(placements, ldr_path, tier_name=tier_name)

        # --- 4. Render preview PNG -------------------------------------------
        png_filename = f"suggestion_{tier_index}_preview.png"
        png_path = str(tmp_path / png_filename)
        if not placements:
            preview_url = ""  # no preview available for empty tier
        else:
            run_ldview(ldr_path, png_path)
            # preview_url is served from the /static/tmp mount in main.py
            preview_url = f"/static/tmp/{request_id}/{png_filename}"

        # --- 5. Build parts list ---------------------------------------------
        parts_list = _build_parts_list(placements)
        parts_count = sum(pc.qty for pc in parts_list)

        suggestions.append(
            Suggestion(
                id=suggestion_id,
                tier=tier_name,
                preview_url=preview_url,
                parts_count=parts_count,
                parts_list=parts_list,
            )
        )

    return suggestions

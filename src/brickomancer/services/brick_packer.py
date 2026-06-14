"""Brick packer — greedy layer-by-layer LEGO brick placement algorithm.

Public API
----------
pack(voxel_grid, color_id) -> list[BrickPlacement]
    Greedy layer-by-layer placement with masonry offset, interlocking check,
    and connectivity repair.

interlocking_check(placements, layer) -> list[BrickPlacement]
    Verify and repair interlocking for a single layer (called internally by pack).

connectivity_repair(placements) -> list[BrickPlacement]
    Find bricks at y>0 with no stud connection to layer y-1 and force-insert
    1×1 bricks to restore structural continuity.
"""

import numpy as np

from brickomancer.models.brick import BRICK_PART_IDS, BRICK_TYPES, TILE_PART_IDS, BrickPlacement

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _footprint(bp: BrickPlacement) -> set[tuple[int, int]]:
    """Return the set of stud positions (x, z) covered by a brick."""
    return {(bp.x + dx, bp.z + dz) for dx in range(bp.width) for dz in range(bp.length)}


def _has_connection(bp: BrickPlacement, below_footprints: set[tuple[int, int]]) -> bool:
    """Return True if bp shares ≥1 stud with any brick in the layer below."""
    return bool(_footprint(bp) & below_footprints)


def _collect_footprints(placements: list[BrickPlacement], layer: int) -> set[tuple[int, int]]:
    """Return the union of all stud positions for bricks on *layer*."""
    result: set[tuple[int, int]] = set()
    for bp in placements:
        if bp.y == layer:
            result |= _footprint(bp)
    return result


def _apply_surface_tiles(placements: list[BrickPlacement]) -> list[BrickPlacement]:
    """Replace top-surface bricks with tile variants for a smooth finished face.

    A brick is top-surface if every stud it covers is at the highest placed
    layer for that (x, z) column. Tiles share the same footprint and LDraw
    coordinates as standard bricks but have no studs on top.
    """
    top_y_per_stud: dict[tuple[int, int], int] = {}
    for bp in placements:
        for sx, sz in _footprint(bp):
            key = (sx, sz)
            if key not in top_y_per_stud or bp.y > top_y_per_stud[key]:
                top_y_per_stud[key] = bp.y

    result: list[BrickPlacement] = []
    for bp in placements:
        tile_id = TILE_PART_IDS.get((bp.width, bp.length))
        if tile_id and all(top_y_per_stud.get(s) == bp.y for s in _footprint(bp)):
            result.append(
                BrickPlacement(
                    part_id=tile_id,
                    color_id=bp.color_id,
                    x=bp.x,
                    y=bp.y,
                    z=bp.z,
                    width=bp.width,
                    length=bp.length,
                )
            )
        else:
            result.append(bp)
    return result


# ---------------------------------------------------------------------------
# Public helpers (also used by tests)
# ---------------------------------------------------------------------------


def interlocking_check(placements: list[BrickPlacement], layer: int) -> list[BrickPlacement]:
    """Check and repair interlocking for bricks at a given layer.

    For each brick in *layer* that has no connection to *layer - 1*, remove it
    and try to replace it with 1×1 bricks that DO connect.  The primary packing
    loop already enforces connectivity, so this function is a safety net for
    edge cases.

    Args:
        placements: List of BrickPlacement objects (may span multiple layers).
        layer: The layer index to check.

    Returns:
        Updated list[BrickPlacement] with interlocking repairs applied.
    """
    if layer == 0:
        return placements

    below_footprints = _collect_footprints(placements, layer - 1)
    if not below_footprints:
        return placements

    result: list[BrickPlacement] = []
    for bp in placements:
        if bp.y != layer:
            result.append(bp)
            continue
        if _has_connection(bp, below_footprints):
            result.append(bp)
        else:
            # Replace disconnected brick with connected 1×1 bricks
            for sx, sz in _footprint(bp):
                if (sx, sz) in below_footprints:
                    result.append(
                        BrickPlacement(
                            part_id=BRICK_PART_IDS[(1, 1)],
                            color_id=bp.color_id,
                            x=sx,
                            y=layer,
                            z=sz,
                            width=1,
                            length=1,
                        )
                    )
    return result


def connectivity_repair(placements: list[BrickPlacement]) -> list[BrickPlacement]:
    """Find and repair floating bricks by inserting 1×1 bridge pillars.

    Bricks at y>0 that share no stud with any brick in layer y-1 are
    force-connected by inserting a 1×1 at the nearest stud in the layer below.

    Args:
        placements: List of BrickPlacement objects.

    Returns:
        Updated list[BrickPlacement] with connectivity repairs applied.
    """
    if not placements:
        return placements

    max_y = max(bp.y for bp in placements)
    to_remove: set[int] = set()  # indices of disconnected bricks to replace
    bridge_bricks: list[BrickPlacement] = []
    bridge_positions: set[tuple[int, int, int]] = set()  # (x, y, z) dedup

    for y in range(1, max_y + 1):
        below_fps = _collect_footprints(placements, y - 1)
        if not below_fps:
            continue
        for i, bp in enumerate(placements):
            if bp.y != y:
                continue
            if not _has_connection(bp, below_fps):
                to_remove.add(i)
                # Find the nearest stud in below_fps to this brick's centroid
                cx = bp.x + bp.width / 2.0
                cz = bp.z + bp.length / 2.0
                nearest = min(below_fps, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cz) ** 2)
                pos = (nearest[0], y, nearest[1])
                if pos not in bridge_positions:
                    bridge_positions.add(pos)
                    bridge_bricks.append(
                        BrickPlacement(
                            part_id=BRICK_PART_IDS[(1, 1)],
                            color_id=bp.color_id,
                            x=nearest[0],
                            y=y,
                            z=nearest[1],
                            width=1,
                            length=1,
                        )
                    )

    filtered = [bp for i, bp in enumerate(placements) if i not in to_remove]
    occupied: set[tuple[int, int, int]] = {
        (sx, bp.y, sz) for bp in filtered for sx, sz in _footprint(bp)
    }
    return filtered + [b for b in bridge_bricks if (b.x, b.y, b.z) not in occupied]


# ---------------------------------------------------------------------------
# Main packer
# ---------------------------------------------------------------------------


def pack(
    voxel_grid: np.ndarray,
    color_id: int = 15,
    brick_set: list[tuple[int, int]] | None = None,
) -> list[BrickPlacement]:
    """Pack a voxel grid into a list of BrickPlacements.

    Greedy layer-by-layer placement with:
    - Masonry offset (odd layers shifted +1 in X)
    - Connectivity enforcement: each brick at y>0 must share ≥1 stud with the
      layer below; if no brick type achieves this, fall through and rely on
      connectivity_repair.
    - Connectivity repair pass after all layers are placed.

    Args:
        voxel_grid: numpy.ndarray[bool] of shape (X, Y, Z) where True = occupied.
        color_id: LDraw color ID to assign to all bricks (default 15 = white).
        brick_set: Optional list of (width, length) tuples. Defaults to BRICK_TYPES.

    Returns:
        list[BrickPlacement]
    """
    if brick_set is None:
        brick_set = BRICK_TYPES

    grid = np.asarray(voxel_grid, dtype=bool)
    if grid.ndim != 3:
        raise ValueError(f"voxel_grid must be 3-D, got shape {grid.shape}")

    X, Y, Z = grid.shape
    placements: list[BrickPlacement] = []

    for y in range(Y):
        # covered[x, z] tracks which stud positions have already been filled
        covered = np.zeros((X, Z), dtype=bool)

        # Footprint of all bricks already placed in layer y-1
        below_fps: set[tuple[int, int]] = _collect_footprints(placements, y - 1) if y > 0 else set()

        # Masonry offset: odd layers start the scan 1 stud into X to achieve
        # interlocking.  We scan [x_offset..X) first then [0..x_offset) so
        # every position is still visited and no voxel is skipped.
        x_offset = 1 if (y % 2 == 1) else 0
        x_order = list(range(x_offset, X)) + list(range(0, x_offset))

        for x in x_order:
            for z in range(Z):
                if covered[x, z] or not grid[x, y, z]:
                    continue

                placed = False
                for w, ln in brick_set:
                    # Try normal orientation (w along X, ln along Z),
                    # then rotated (ln along X, w along Z) only if the
                    # rotated shape also exists in BRICK_PART_IDS.
                    orientations: list[tuple[int, int]] = [(w, ln)]
                    if w != ln and (ln, w) in BRICK_PART_IDS:
                        orientations.append((ln, w))

                    for bw, bl in orientations:
                        # On odd layers try a half-brick-offset start first so
                        # joints don't align with the layer below (true masonry).
                        if y % 2 == 1 and bw > 1:
                            half = bw // 2
                            starts = [s for s in [x - half, x] if s >= 0]
                        else:
                            starts = [x]

                        for start_x in starts:
                            # Check bounds
                            if start_x + bw > X or z + bl > Z:
                                continue

                            # Check that all stud positions are occupied in the voxel grid
                            region = grid[start_x : start_x + bw, y, z : z + bl]
                            if not region.all():
                                continue

                            # Check none already covered
                            cov_region = covered[start_x : start_x + bw, z : z + bl]
                            if cov_region.any():
                                continue

                            # Build candidate brick
                            candidate = BrickPlacement(
                                part_id=BRICK_PART_IDS[(bw, bl)],
                                color_id=color_id,
                                x=start_x,
                                y=y,
                                z=z,
                                width=bw,
                                length=bl,
                            )

                            # Connectivity check for layers above ground
                            if y > 0 and below_fps:
                                if not _has_connection(candidate, below_fps):
                                    continue  # try next start or smaller brick

                            # Accept
                            placements.append(candidate)
                            covered[start_x : start_x + bw, z : z + bl] = True
                            placed = True
                            break  # break start_x loop

                        if placed:
                            break  # break orientations loop

                    if placed:
                        break  # break brick_set loop

                if not placed:
                    # Fall through: single 1×1 without connectivity guarantee
                    # (connectivity_repair will fix these)
                    candidate_1x1 = BrickPlacement(
                        part_id=BRICK_PART_IDS[(1, 1)],
                        color_id=color_id,
                        x=x,
                        y=y,
                        z=z,
                        width=1,
                        length=1,
                    )
                    placements.append(candidate_1x1)
                    covered[x, z] = True

    # Final connectivity repair pass, then tile the top surface
    placements = connectivity_repair(placements)
    return _apply_surface_tiles(placements)

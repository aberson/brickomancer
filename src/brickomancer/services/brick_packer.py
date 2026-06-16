"""Brick packer â€” greedy layer-by-layer LEGO brick placement algorithm.

Public API
----------
pack(voxel_grid, color_id) -> list[BrickPlacement]
    Greedy layer-by-layer placement with per-Z-row starter pre-pass masonry,
    interlocking check, and connectivity repair.

interlocking_check(placements, layer) -> list[BrickPlacement]
    Verify and repair interlocking for a single layer (called internally by pack).

connectivity_repair(placements) -> list[BrickPlacement]
    Find bricks at y>0 with no stud connection to layer y-1 and force-insert
    1Ã—1 bricks to restore structural continuity.
"""

import math

import numpy as np

from brickomancer.models.brick import BRICK_PART_IDS, BRICK_TYPES, TILE_PART_IDS, BrickPlacement

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _footprint(bp: BrickPlacement) -> set[tuple[int, int]]:
    """Return the set of stud positions (x, z) covered by a brick."""
    return {(bp.x + dx, bp.z + dz) for dx in range(bp.width) for dz in range(bp.length)}


def _has_connection(bp: BrickPlacement, below_footprints: set[tuple[int, int]]) -> bool:
    """Return True if bp shares â‰¥1 stud with any brick in the layer below."""
    return bool(_footprint(bp) & below_footprints)


def _collect_footprints(placements: list[BrickPlacement], layer: int) -> set[tuple[int, int]]:
    """Return the union of all stud positions for bricks on *layer*."""
    result: set[tuple[int, int]] = set()
    for bp in placements:
        if bp.y == layer:
            result |= _footprint(bp)
    return result


def _boundary_voxels(layer_slice: np.ndarray) -> set[tuple[int, int]]:
    """Return (x, z) positions with fewer than 3 occupied XZ-plane neighbors."""
    X, Z = layer_slice.shape
    boundary: set[tuple[int, int]] = set()
    for x in range(X):
        for z in range(Z):
            if not layer_slice[x, z]:
                continue
            neighbors = 0
            for dx, dz in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, nz = x + dx, z + dz
                if 0 <= nx < X and 0 <= nz < Z and layer_slice[nx, nz]:
                    neighbors += 1
            if neighbors < 3:
                boundary.add((x, z))
    return boundary


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
        is_top_surface = all(top_y_per_stud.get(s) == bp.y for s in _footprint(bp))
        if not is_top_surface:
            result.append(bp)
            continue

        tile_id = TILE_PART_IDS.get((bp.width, bp.length))
        if tile_id:
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
            strip_tile_id = TILE_PART_IDS.get((1, bp.length))
            if strip_tile_id:
                for dx in range(bp.width):
                    result.append(
                        BrickPlacement(
                            part_id=strip_tile_id,
                            color_id=bp.color_id,
                            x=bp.x + dx,
                            y=bp.y,
                            z=bp.z,
                            width=1,
                            length=bp.length,
                        )
                    )
            else:
                unit_tile_id = TILE_PART_IDS.get((1, 1))
                if unit_tile_id:
                    for dx in range(bp.width):
                        for dz in range(bp.length):
                            result.append(
                                BrickPlacement(
                                    part_id=unit_tile_id,
                                    color_id=bp.color_id,
                                    x=bp.x + dx,
                                    y=bp.y,
                                    z=bp.z + dz,
                                    width=1,
                                    length=1,
                                )
                            )
                else:
                    result.append(bp)
    return result


def _remove_isolated_pillars(placements: list[BrickPlacement]) -> list[BrickPlacement]:
    stud_positions_by_layer: dict[int, set[tuple[int, int]]] = {}
    for bp in placements:
        if bp.y not in stud_positions_by_layer:
            stud_positions_by_layer[bp.y] = set()
        for sx, sz in _footprint(bp):
            stud_positions_by_layer[bp.y].add((sx, sz))

    column_stacks: dict[tuple[int, int, int, int], list[int]] = {}
    for bp in placements:
        key = (bp.x, bp.z, bp.width, bp.length)
        if key not in column_stacks:
            column_stacks[key] = []
        column_stacks[key].append(bp.y)

    bricks_to_remove: set[tuple[int, int, int, int, int]] = set()
    for (x, z, w, ln), layers in column_stacks.items():
        if len(layers) < 2:
            continue

        footprint_studs = {(x + dx, z + dz) for dx in range(w) for dz in range(ln)}
        adjacent_studs: set[tuple[int, int]] = set()
        for sx, sz in footprint_studs:
            for dnx in [-1, 0, 1]:
                for dnz in [-1, 0, 1]:
                    if dnx == 0 and dnz == 0:
                        continue
                    nx, nz = sx + dnx, sz + dnz
                    if (nx, nz) not in footprint_studs:
                        adjacent_studs.add((nx, nz))

        min_y = min(layers)
        isolated_layers = {
            y for y in layers
            if y != min_y and not bool(adjacent_studs & stud_positions_by_layer.get(y, set()))
        }

        if not isolated_layers:
            continue

        for y in isolated_layers:
            bricks_to_remove.add((x, z, w, ln, y))

    pass1: list[BrickPlacement] = [
        bp for bp in placements
        if (bp.x, bp.z, bp.width, bp.length, bp.y) not in bricks_to_remove
    ]

    global_xz: set[tuple[int, int]] = set()
    xz_layer_count: dict[tuple[int, int], set[int]] = {}
    for bp in pass1:
        for sx, sz in _footprint(bp):
            global_xz.add((sx, sz))
            if (sx, sz) not in xz_layer_count:
                xz_layer_count[(sx, sz)] = set()
            xz_layer_count[(sx, sz)].add(bp.y)

    isolated_xz: set[tuple[int, int]] = set()
    for sx, sz in global_xz:
        if len(xz_layer_count[(sx, sz)]) < 1:
            continue
        neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if not any((sx + dx, sz + dz) in global_xz for dx, dz in neighbors):
            isolated_xz.add((sx, sz))

    if not isolated_xz:
        return pass1

    return [bp for bp in pass1 if bp.y == 0 or not (_footprint(bp) <= isolated_xz)]


def _brace_thin_columns(placements: list[BrickPlacement], color_id: int) -> list[BrickPlacement]:
    all_occupied_xz: set[tuple[int, int]] = set()
    for bp in placements:
        for sx, sz in _footprint(bp):
            all_occupied_xz.add((sx, sz))

    if not all_occupied_xz:
        return placements

    cx = sum(x for x, z in all_occupied_xz) / len(all_occupied_xz)
    cz = sum(z for x, z in all_occupied_xz) / len(all_occupied_xz)

    column_min_y: dict[tuple[int, int], int] = {}
    column_layers: dict[tuple[int, int], set[int]] = {}
    for bp in placements:
        for sx, sz in _footprint(bp):
            key = (sx, sz)
            if key not in column_min_y or bp.y < column_min_y[key]:
                column_min_y[key] = bp.y
            if key not in column_layers:
                column_layers[key] = set()
            column_layers[key].add(bp.y)

    existing_positions: set[tuple[int, int, int]] = {
        (sx, bp.y, sz) for bp in placements for sx, sz in _footprint(bp)
    }

    support_bricks: list[BrickPlacement] = []
    support_positions: set[tuple[int, int, int]] = set()

    for xz in all_occupied_xz:
        x, z = xz
        if len(column_layers.get(xz, set())) < 2:
            continue
        cardinal = [(x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)]
        if any(n in all_occupied_xz for n in cardinal):
            continue

        min_y = column_min_y[xz]
        candidates = sorted(cardinal, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cz) ** 2)

        for nx, nz in candidates:
            pos = (nx, min_y, nz)
            if pos not in existing_positions and pos not in support_positions:
                support_positions.add(pos)
                support_bricks.append(
                    BrickPlacement(
                        part_id=BRICK_PART_IDS[(1, 1)],
                        color_id=color_id,
                        x=nx,
                        y=min_y,
                        z=nz,
                        width=1,
                        length=1,
                    )
                )
                break

    return placements + support_bricks


def _fill_central_hub(
    placements: list[BrickPlacement], grid: np.ndarray, color_id: int
) -> list[BrickPlacement]:
    X, Y, Z = grid.shape

    occupied = np.argwhere(grid)
    if occupied.size == 0:
        return placements

    cx = float(np.mean(occupied[:, 0]))
    cz = float(np.mean(occupied[:, 2]))

    hub_radius = math.ceil(min(X, Z) * 0.30)

    layers_with_placements: set[int] = {bp.y for bp in placements}

    covered: set[tuple[int, int, int]] = set()
    for bp in placements:
        for sx, sz in _footprint(bp):
            covered.add((sx, bp.y, sz))

    new_bricks: list[BrickPlacement] = []
    new_positions: set[tuple[int, int, int]] = set()

    for y in layers_with_placements:
        for x in range(X):
            for z in range(Z):
                dist = ((x - cx) ** 2 + (z - cz) ** 2) ** 0.5
                if dist > hub_radius:
                    continue
                if not grid[x, y, z]:
                    continue
                pos = (x, y, z)
                if pos in covered or pos in new_positions:
                    continue
                new_positions.add(pos)
                new_bricks.append(
                    BrickPlacement(
                        part_id=BRICK_PART_IDS[(1, 1)],
                        color_id=color_id,
                        x=x,
                        y=y,
                        z=z,
                        width=1,
                        length=1,
                    )
                )

    return placements + new_bricks


def _add_floor_support(placements: list[BrickPlacement], color_id: int) -> list[BrickPlacement]:
    above_ground_xz: set[tuple[int, int]] = set()
    for bp in placements:
        if bp.y >= 1:
            above_ground_xz |= _footprint(bp)

    floor_xz: set[tuple[int, int]] = set()
    for bp in placements:
        if bp.y == 0:
            floor_xz |= _footprint(bp)

    missing = above_ground_xz - floor_xz
    if not missing:
        return placements

    support_bricks = [
        BrickPlacement(
            part_id=BRICK_PART_IDS[(1, 1)],
            color_id=color_id,
            x=x,
            y=0,
            z=z,
            width=1,
            length=1,
        )
        for x, z in missing
    ]
    return placements + support_bricks


# ---------------------------------------------------------------------------
# Public helpers (also used by tests)
# ---------------------------------------------------------------------------


def interlocking_check(placements: list[BrickPlacement], layer: int) -> list[BrickPlacement]:
    """Check and repair interlocking for bricks at a given layer.

    For each brick in *layer* that has no connection to *layer - 1*, remove it
    and try to replace it with 1Ã—1 bricks that DO connect.  The primary packing
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
            # Replace disconnected brick with connected 1Ã—1 bricks
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
    """Find and repair floating bricks by inserting 1Ã—1 bridge pillars.

    Bricks at y>0 that share no stud with any brick in layer y-1 are
    force-connected by inserting a 1Ã—1 at the nearest stud in the layer below.

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
    - Per-Z-row starter pre-pass masonry: on odd layers (y % 2 == 1), place a
      1Ã—1 brick at the leftmost occupied stud in each Z row before the main
      greedy scan. This forces the main scan to start from leftmost+1, shifting
      all seam positions relative to even layers and producing true interlocking.
      Even layers (y % 2 == 0) use a standard scan from x=0 with no pre-pass.
    - Connectivity enforcement: each brick at y>0 must share â‰¥1 stud with the
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

    _MIN_FOOTPRINT = 2
    if X < _MIN_FOOTPRINT or Z < _MIN_FOOTPRINT:
        px = max(0, _MIN_FOOTPRINT - X)
        pz = max(0, _MIN_FOOTPRINT - Z)
        grid = np.pad(grid, ((0, px), (0, 0), (0, pz)), mode="edge")
        X, Z = grid.shape[0], grid.shape[2]

    placements: list[BrickPlacement] = []

    for y in range(Y):
        # covered[x, z] tracks which stud positions have already been filled
        covered = np.zeros((X, Z), dtype=bool)

        # Footprint of all bricks already placed in layer y-1
        below_fps: set[tuple[int, int]] = _collect_footprints(placements, y - 1) if y > 0 else set()

        # Boundary voxels for this layer: positions with < 3 occupied XZ neighbors.
        # These receive only 1Ã—1 bricks to preserve arm-tip and edge geometry.
        boundary = _boundary_voxels(grid[:, y, :])

        # Per-Z-row starter pre-pass for odd layers only.
        # For each Z row, find the leftmost occupied, unplaced stud and place a
        # 1Ã—1 there. This shifts the greedy scan's effective start to x=1 in
        # every row, producing seam positions that differ from even layers.
        if y % 2 == 1:
            for z in range(Z):
                for x in range(X):
                    if grid[x, y, z] and not covered[x, z]:
                        # Connectivity check before placing pre-pass 1Ã—1
                        candidate = BrickPlacement(
                            part_id=BRICK_PART_IDS[(1, 1)],
                            color_id=color_id,
                            x=x,
                            y=y,
                            z=z,
                            width=1,
                            length=1,
                        )
                        if y > 0 and below_fps and not _has_connection(candidate, below_fps):
                            break  # no connected starter in this Z row; skip pre-pass for it
                        placements.append(candidate)
                        covered[x, z] = True
                        break  # one starter per Z row

        # Main greedy scan: standard x-first order
        for x in range(X):
            for z in range(Z):
                if covered[x, z] or not grid[x, y, z]:
                    continue

                placed = False
                effective_brick_set = [(1, 1)] if (x, z) in boundary else brick_set
                for w, ln in effective_brick_set:
                    orientations: list[tuple[int, int]] = [(w, ln)]
                    if w != ln and (ln, w) in BRICK_PART_IDS:
                        orientations.append((ln, w))

                    for bw, bl in orientations:
                        # Check bounds
                        if x + bw > X or z + bl > Z:
                            continue

                        # Check that all stud positions are occupied in the voxel grid
                        region = grid[x : x + bw, y, z : z + bl]
                        if not region.all():
                            continue

                        # Check none already covered
                        cov_region = covered[x : x + bw, z : z + bl]
                        if cov_region.any():
                            continue

                        # Build candidate brick
                        candidate = BrickPlacement(
                            part_id=BRICK_PART_IDS[(bw, bl)],
                            color_id=color_id,
                            x=x,
                            y=y,
                            z=z,
                            width=bw,
                            length=bl,
                        )

                        # Connectivity check for layers above ground
                        if y > 0 and below_fps:
                            if not _has_connection(candidate, below_fps):
                                continue  # try next orientation or smaller brick

                        # Accept
                        placements.append(candidate)
                        covered[x : x + bw, z : z + bl] = True
                        placed = True
                        break  # break orientations loop

                    if placed:
                        break  # break brick_set loop

                if not placed:
                    # Fall through: single 1Ã—1 without connectivity guarantee
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

    # Remove isolated pillars, repair connectivity, add floor support, tile top surface
    placements = _remove_isolated_pillars(placements)
    placements = _fill_central_hub(placements, grid, color_id)
    placements = connectivity_repair(placements)
    placements = _add_floor_support(placements, color_id)
    placements = _brace_thin_columns(placements, color_id)
    return _apply_surface_tiles(placements)

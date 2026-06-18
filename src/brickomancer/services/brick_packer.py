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

import networkx as nx
import numpy as np

from brickomancer.models.brick import (
    BRICK_PART_IDS,
    BRICK_TYPES,
    MIN_GRID_DIM,
    TILE_PART_IDS,
    BrickPlacement,
)

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
                nbx, nbz = x + dx, z + dz
                if 0 <= nbx < X and 0 <= nbz < Z and layer_slice[nbx, nbz]:
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

        # Tiles replace a brick ONE-FOR-ONE only (same footprint). The old strip/unit
        # fallback SPLIT a no-exact-tile brick (e.g. a top-layer (2,3) or a (2,1) bond)
        # into separate 1x1/strip tiles -- which severs any connectivity that brick was
        # the sole span for. With the cap-above merge gone, load-bearing bricks now sit
        # ON the top surface, so splitting them re-fragments the build (cube (7,2,3) ->
        # 4 components). Keep any brick without an exact tile as a brick (studs visible
        # on top is a cosmetic cost; a severed bond is a structural defect).
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
                    nbx, nbz = sx + dnx, sz + dnz
                    if (nbx, nbz) not in footprint_studs:
                        adjacent_studs.add((nbx, nbz))

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

        for nbx, nbz in candidates:
            pos = (nbx, min_y, nbz)
            if pos not in existing_positions and pos not in support_positions:
                support_positions.add(pos)
                support_bricks.append(
                    BrickPlacement(
                        part_id=BRICK_PART_IDS[(1, 1)],
                        color_id=color_id,
                        x=nbx,
                        y=min_y,
                        z=nbz,
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
# Phase B: connectivity-graph analysis
# ---------------------------------------------------------------------------
#
# Makes structural soundness something the packer can *see* (vs v1's post-hoc
# heuristic patches). A brick is a node keyed by its (x, y, z, width, length)
# position+dims; an edge joins two bricks on ADJACENT layers (|Ya - Yb| == 1)
# that share >= 1 stud footprint -- i.e. one rests on the other. There are NO
# same-layer lateral edges: in real LEGO, studs only bond vertically, so two
# side-by-side bricks are NOT structurally bonded unless a brick above or below
# spans both. This is also what makes articulation points meaningful for Step 4.

_BrickKey = tuple[int, int, int, int, int]


def _brick_key(bp: BrickPlacement) -> _BrickKey:
    """Stable graph node key: position + dims (unique per placed brick)."""
    return (bp.x, bp.y, bp.z, bp.width, bp.length)


def build_connectivity_graph(placements: list[BrickPlacement]) -> nx.Graph:
    """Build the brick connectivity graph (nodes = bricks, edges = stud bonds).

    Node key is ``(x, y, z, width, length)``. An edge joins two bricks on
    adjacent layers that share >= 1 stud. Raises if two placements collide on the
    same key (the one-brick-per-position-and-dims assumption -- loud so a future
    bug surfaces here rather than silently merging nodes).
    """
    graph: nx.Graph = nx.Graph()
    by_layer: dict[int, list[BrickPlacement]] = {}
    for bp in placements:
        key = _brick_key(bp)
        if key in graph:
            raise AssertionError(f"duplicate brick key {key} in connectivity graph")
        graph.add_node(key)
        by_layer.setdefault(bp.y, []).append(bp)

    for y, layer_bricks in by_layer.items():
        above = by_layer.get(y + 1)
        if not above:
            continue
        for lower in layer_bricks:
            lower_fp = _footprint(lower)
            for upper in above:
                if lower_fp & _footprint(upper):
                    graph.add_edge(_brick_key(lower), _brick_key(upper))
    return graph


def connected_components_list(placements: list[BrickPlacement]) -> list[set[_BrickKey]]:
    """Return the connectivity graph's connected components as sets of brick keys."""
    return list(nx.connected_components(build_connectivity_graph(placements)))


def connected_component_count(placements: list[BrickPlacement]) -> int:
    """Return the number of connected components (1 = a single bonded assembly)."""
    if not placements:
        return 0
    return nx.number_connected_components(build_connectivity_graph(placements))


def unsupported_bricks(placements: list[BrickPlacement]) -> list[BrickPlacement]:
    """Return bricks at y>0 that share no stud with the layer below (would float).

    "Supported" means LEGO-attached: a brick is supported if it grips >= 1 stud of
    the layer below -- the real-world attachment rule (a 2x2 brick held by a single
    stud is stable). It does NOT require every stud to be backed; a brick may
    legitimately overhang (e.g. a merge cap whose 2 bonding studs sit on towers and
    whose other 2 studs cantilever over empty space). Distinct from connectivity: a
    brick can belong to the main component via a vertical neighbor yet still be
    individually unsupported. Ground-layer bricks (y == 0) are always supported.
    """
    by_layer_fp: dict[int, set[tuple[int, int]]] = {}
    for bp in placements:
        by_layer_fp.setdefault(bp.y, set()).update(_footprint(bp))

    result: list[BrickPlacement] = []
    for bp in placements:
        if bp.y == 0:
            continue
        below = by_layer_fp.get(bp.y - 1, set())
        if not (_footprint(bp) & below):
            result.append(bp)
    return result


def articulation_points(placements: list[BrickPlacement]) -> list[BrickPlacement]:
    """Return cut-vertex bricks (removal disconnects the graph) -- structural weak points.

    Computed here in Step 3; targeted for elimination at arm tips in Step 4's
    split/re-merge pass. Keys are mapped back to their BrickPlacement objects.
    """
    graph = build_connectivity_graph(placements)
    key_to_bp = {_brick_key(bp): bp for bp in placements}
    return [key_to_bp[k] for k in nx.articulation_points(graph)]


def _cap_positions(
    s: tuple[int, int], n: tuple[int, int]
) -> list[tuple[int, int]]:
    """2x2 anchor positions (min-corner) whose block covers both adjacent studs s, n.

    Two studs one apart fit in a 2x2 block two ways (the overhang goes either side
    of the shared axis). Returning both lets the caller pick the one that does not
    collide with an already-placed cap.
    """
    (sx, sz), (nx_, nz_) = s, n
    cx, cz = min(sx, nx_), min(sz, nz_)
    if sx == nx_:  # z-adjacent: overhang in +x or -x
        return [(cx, cz), (cx - 1, cz)]
    return [(cx, cz), (cx, cz - 1)]  # x-adjacent: overhang in +z or -z


def _seam_set(placements: list[BrickPlacement], layer: int) -> set[int]:
    """The masonry seam signature of a layer: the set of x+width edge positions."""
    return {bp.x + bp.width for bp in placements if bp.y == layer}


def _brick_at(
    placements: list[BrickPlacement], x: int, y: int, z: int
) -> BrickPlacement | None:
    """Return the (unique) brick covering stud (x, z) on layer y, or None."""
    for bp in placements:
        if bp.y == y and (x, z) in _footprint(bp):
            return bp
    return None


def _col_1x1_layers(placements: list[BrickPlacement], col: tuple[int, int]) -> set[int]:
    """Layers at which column *col* is covered by a lone 1x1 brick (clean-swap layers)."""
    cx, cz = col
    return {
        bp.y for bp in placements
        if bp.width == 1 and bp.length == 1 and bp.x == cx and bp.z == cz
    }


def _col_layers(placements: list[BrickPlacement], col: tuple[int, int]) -> set[int]:
    """All layers at which column *col* is occupied (by any brick)."""
    cx, cz = col
    return {bp.y for bp in placements if (cx, cz) in _footprint(bp)}


def _recover_except(
    brick: BrickPlacement, freed: tuple[int, int], color_id: int
) -> list[BrickPlacement]:
    """1x1 bricks re-covering *brick*'s footprint except the *freed* stud.

    Used when a bond decomposes a multi-stud anchor brick: the bond takes the freed
    stud, and the brick's other studs are re-laid as 1x1s so coverage is preserved.
    """
    return [
        BrickPlacement(BRICK_PART_IDS[(1, 1)], color_id, sx, brick.y, sz, 1, 1)
        for sx, sz in _footprint(brick)
        if (sx, sz) != freed
    ]


def _bond_guards_ok(
    before: list[BrickPlacement],
    after: list[BrickPlacement],
    *,
    require_merge: bool = True,
) -> bool:
    """Validate a candidate bond: no added height, no new float, right component delta.

    - height guard: enforces the in-volume invariant (a bond must not raise max y).
    - unsupported guard: the BrickGPT-style physics rollback (no new floating brick).
    - component guard: a PRIMARY bond must STRICTLY reduce the component count -- it
      exists to merge two fragments into one. Strictness is load-bearing: a decompose
      that frees a hub stud may simultaneously merge one pair AND sever another
      (e.g. shattering a z-extend's (1,N) span that was holding an arm), netting zero
      change; non-strict "no increase" would wrongly accept that. A redundant
      de-articulation bond (require_merge=False) must instead leave the count
      unchanged (it adds a cycle, never a merge or a split).
    """
    if max((bp.y for bp in after), default=0) > max((bp.y for bp in before), default=0):
        return False
    if len(unsupported_bricks(after)) > len(unsupported_bricks(before)):
        return False
    before_n = connected_component_count(before)
    after_n = connected_component_count(after)
    if require_merge:
        return after_n < before_n
    return after_n == before_n


def _z_extension(
    anchor: BrickPlacement, frag_col: tuple[int, int]
) -> BrickPlacement | None:
    """If *frag_col* extends the z-run of width-1 z-brick *anchor* by one stud (and
    the result is a valid part length <= 4), return the grown brick; else None.

    This is the seam-neutral hub primitive: growing a (1,N) z-brick to (1,N+1) to
    absorb a z-adjacent fragment tower keeps width 1 (so x+width is unchanged) AND
    reuses the anchor's existing layer (so no layer budget is consumed and the
    anchor's span -- e.g. a hub column's link to the far arm -- is preserved).
    """
    fx, fz = frag_col
    if anchor.width != 1 or anchor.x != fx:
        return None
    new_len = anchor.length + 1
    if (1, new_len) not in BRICK_PART_IDS:
        return None
    if fz == anchor.z - 1:  # extend downward in z
        new_z = fz
    elif fz == anchor.z + anchor.length:  # extend upward in z
        new_z = anchor.z
    else:
        return None
    return BrickPlacement(
        BRICK_PART_IDS[(1, new_len)], anchor.color_id, fx, anchor.y, new_z, 1, new_len
    )


# Bond strategies, in priority order. Lower rank wins so the seam-safe paths (clean
# swaps, then the seam-neutral z-extend) are exhausted before any seam-affecting x-bond
# or any decompose. z-extend precedes z-decompose because extending preserves the
# anchor brick's span (critical for saturated hubs) whereas decomposing shatters it.
# NOTE: x_clean intentionally outranks z_decompose -- a clean 2-brick x-swap is less
# disruptive to existing masonry structure than shattering a wide z-brick into 1x1s,
# and on solid masonry grids the seam-gate below keeps x-bonds from firing anyway.
_RANK_Z_CLEAN, _RANK_Z_EXTEND, _RANK_X_CLEAN, _RANK_Z_DECOMPOSE, _RANK_X_DECOMPOSE = range(5)


def _bond_candidate(
    current: list[BrickPlacement],
    frag_col: tuple[int, int],
    anchor_col: tuple[int, int],
    layer: int,
    color_id: int,
) -> tuple[int, list[BrickPlacement]] | None:
    """Build ONE candidate bond of frag_col->anchor_col at *layer*, if any strategy
    applies. Returns (rank, new_placements) or None.

    The fragment side must be a lone 1x1 (fragment towers always are). The anchor
    side may be a lone 1x1 (clean swap), a width-1 z-brick (z-extend), or any
    multi-stud brick (decompose). The result is validated by the shared bond guards.
    """
    frag = _brick_at(current, frag_col[0], layer, frag_col[1])
    anchor = _brick_at(current, anchor_col[0], layer, anchor_col[1])
    if frag is None or anchor is None or frag is anchor:
        return None
    if (frag.width, frag.length) != (1, 1):
        return None

    is_z = frag_col[0] == anchor_col[0]
    anchor_clean = (anchor.width, anchor.length) == (1, 1)
    base = [bp for bp in current if bp is not frag and bp is not anchor]

    if is_z:
        if anchor_clean:
            rank = _RANK_Z_CLEAN
            new = base + [_make_z_bond(frag_col, anchor_col, layer, color_id)]
        else:
            grown = _z_extension(anchor, frag_col)
            if grown is not None:
                rank = _RANK_Z_EXTEND
                new = base + [grown]
            else:
                rank = _RANK_Z_DECOMPOSE
                new = (
                    base
                    + _recover_except(anchor, anchor_col, color_id)
                    + [_make_z_bond(frag_col, anchor_col, layer, color_id)]
                )
    else:
        # Seam-reuse gate: an x-bond (width 2) erases the seam at min_x+1, so it is only
        # placed when its right edge (min_x+2) is ALREADY a seam at this layer -- it then
        # introduces no novel seam column. This protects the masonry ABAB signature on
        # solid grids (where a z-bond is also preferred and usually wins). The cost: a
        # thin Z<=2 block whose only fragment adjacency is x and whose seam-reuse fails
        # defers to the cap-above fallback (a documented +1 height on such slabs) rather
        # than reshape the interlocking the greedy fill produced.
        if (min(frag_col[0], anchor_col[0]) + 2) not in _seam_set(current, layer):
            return None
        rank = _RANK_X_CLEAN if anchor_clean else _RANK_X_DECOMPOSE
        recover = [] if anchor_clean else _recover_except(anchor, anchor_col, color_id)
        new = base + recover + [_make_x_bond(frag_col, anchor_col, layer, color_id)]

    if not _bond_guards_ok(current, new):
        return None
    return rank, new


def _make_z_bond(
    col_a: tuple[int, int], col_b: tuple[int, int], layer: int, color_id: int
) -> BrickPlacement:
    """A (1,2) z-bond covering two z-adjacent columns (seam-neutral, width 1)."""
    return BrickPlacement(
        BRICK_PART_IDS[(1, 2)], color_id, col_a[0], layer, min(col_a[1], col_b[1]), 1, 2
    )


def _make_x_bond(
    col_a: tuple[int, int], col_b: tuple[int, int], layer: int, color_id: int
) -> BrickPlacement:
    """A bond-only (2,1) x-bond covering two x-adjacent columns (part 3004 rotated)."""
    return BrickPlacement(
        BRICK_PART_IDS[(2, 1)], color_id, min(col_a[0], col_b[0]), layer, col_a[1], 2, 1
    )


def _bond_one_edge(
    current: list[BrickPlacement],
    options: list[tuple[tuple[int, int], tuple[int, int]]],
    color_id: int,
) -> list[BrickPlacement] | None:
    """Bond one component pair in-volume; return the new list or None if deferred.

    Enumerates every (column pair, shared layer, orientation) candidate, builds the
    best-ranked valid bond per slot, and applies the globally lowest-ranked one
    (clean z first, ... x-decompose last; ties broken deterministically by layer then
    columns). A single bond merges the two components; "no clean in-volume bond"
    leaves the edge for the caller's cap-above fallback (never needed for the
    cube/masonry/plus-star fixtures, which fully bond in-volume at zero added height).
    """
    candidates: list[tuple[int, int, tuple[int, int], tuple[int, int], list[BrickPlacement]]] = []
    for col_a, col_b in options:
        shared = _col_layers(current, col_a) & _col_layers(current, col_b)
        for layer in sorted(shared):
            for frag_col, anchor_col in ((col_a, col_b), (col_b, col_a)):
                built = _bond_candidate(current, frag_col, anchor_col, layer, color_id)
                if built is not None:
                    rank, new = built
                    candidates.append((rank, layer, frag_col, anchor_col, new))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    return candidates[0][4]


def _component_adjacency(
    placements: list[BrickPlacement],
) -> tuple[
    list[set[_BrickKey]],
    dict[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]]],
    dict[int, set[int]],
]:
    """Components + the inter-component cardinal adjacency graph.

    Returns (components, adjacency, neighbors) where adjacency[pair] lists every
    (col_a, col_b) cardinal column pair bridging the two components, and neighbors
    maps each component index to its adjacent component indices.
    """
    components = connected_components_list(placements)
    key_to_comp = {key: ci for ci, comp in enumerate(components) for key in comp}
    col_comps: dict[tuple[int, int], set[int]] = {}
    for bp in placements:
        ci = key_to_comp[_brick_key(bp)]
        for sx, sz in _footprint(bp):
            col_comps.setdefault((sx, sz), set()).add(ci)

    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], tuple[int, int]]]] = {}
    neighbors: dict[int, set[int]] = {ci: set() for ci in range(len(components))}
    for (sx, sz), cas in col_comps.items():
        for nx_, nz_ in ((sx + 1, sz), (sx, sz + 1)):
            cbs = col_comps.get((nx_, nz_))
            if not cbs:
                continue
            for ca in cas:
                for cb in cbs:
                    if ca == cb:
                        continue
                    pair = (min(ca, cb), max(ca, cb))
                    neighbors[ca].add(cb)
                    neighbors[cb].add(ca)
                    adjacency.setdefault(pair, []).append(((sx, sz), (nx_, nz_)))
    return components, adjacency, neighbors


def _bond_components_in_volume(
    placements: list[BrickPlacement], color_id: int, max_iterations: int = 5
) -> list[BrickPlacement]:
    """Bond disconnected fragment towers into ONE assembly WITHOUT adding height.

    Replaces the cap-above _merge_components. Full-height 1x1 fragment towers (cube
    corners, plus-star arm tips) are bonded into the spine by replacing two 1x1s at a
    shared IN-GRID layer with one 2-wide bond brick -- z-direction (1,2) (seam-neutral)
    or x-direction (2,1) (seam-gated). Every bond sits at an existing layer, so build
    height is unchanged (this is the ~20% overshoot the cap-above merge introduced).

    Algorithm (mirrors the old merge's spanning-tree skeleton):
      1. Components + inter-component adjacency computed ONCE from the input.
      2. Spanning tree rooted at the anchor (most ground bricks, then largest).
      3. Each tree edge is bonded in-volume via _bond_one_edge (z preferred, x
         seam-gated, physics-guarded). Edges with no clean in-volume bond are left
         for the caller's cap-above fallback (rare; never needed for solid/star grids).

    max_iterations is accepted for signature parity with the fallback; the spanning
    tree bonds every reachable component in a single pass.
    """
    current = list(placements)
    if not current or max(bp.y for bp in current) == 0:
        # A flat single-layer build has no vertical structure to bond (it sits on a
        # baseplate); stacking anything would wrongly make it multi-layer.
        return current
    if connected_component_count(current) <= 1:
        return current

    components, adjacency, neighbors = _component_adjacency(current)
    ground = [sum(1 for k in comp if k[1] == 0) for comp in components]
    anchor = max(range(len(components)), key=lambda i: (ground[i], len(components[i])))

    visited = {anchor}
    queue = [anchor]
    tree_edges: list[tuple[int, int]] = []
    while queue:
        u = queue.pop(0)
        for v in sorted(neighbors[u]):
            if v not in visited:
                visited.add(v)
                tree_edges.append((min(u, v), max(u, v)))
                queue.append(v)

    for pair in tree_edges:
        bonded = _bond_one_edge(current, adjacency[pair], color_id)
        if bonded is not None:
            current = bonded
    return current


def _is_arm_tip_brick(bp: BrickPlacement, grid: np.ndarray) -> bool:
    """True if every stud of *bp* lies on a boundary voxel of its grid layer.

    Boundary = a voxel with <3 occupied in-plane neighbors (an arm tip / thin edge --
    the freestanding-tower regions Step 4 must bond into the spine). Out-of-grid
    layers (none, for in-volume bonds) return False.
    """
    _, y_dim, _ = grid.shape
    if not (0 <= bp.y < y_dim):
        return False
    boundary = _boundary_voxels(grid[:, bp.y, :])
    return all((sx, sz) in boundary for sx, sz in _footprint(bp))


def _eliminate_arm_tip_articulations(
    placements: list[BrickPlacement], color_id: int, max_iterations: int = 5
) -> list[BrickPlacement]:
    """Harden single-bond fragments into cycles by adding redundant in-volume bonds.

    A fragment tower joined to the spine by ONE bond is a cut vertex: removing that
    bond re-isolates it. Where the fragment shares a SECOND lone-1x1 layer with an
    adjacent spine column, a redundant z-bond there forms a cycle, so the connection
    no longer hinges on a single brick. Each redundant bond must STRICTLY reduce the
    cut-vertex count and pass the bond guards (no added height, no new float, component
    count unchanged at 1). Bonded to *max_iterations* passes; converges as soon as no
    redundant bond helps.

    Redundant bonds are Z-DIRECTION ONLY -- a (1,2) z-bond is provably seam-neutral
    (width 1, so x+width is unchanged), so this pass can never disturb the masonry
    ABAB signature. An x-bond always erases a seam (min_x+1) and would corrupt the
    masonry seams unless applied symmetrically across same-parity layers; that
    complexity buys nothing here, so x redundancy is simply excluded.

    LIMITATION (geometric, not a defect): a saturated hub -- e.g. the plus-star centre,
    whose 3 layers are all consumed bonding its 4 arms -- and literal 1-wide arm tips
    have no spare layer/neighbour for a redundant z-bond, so a residue of internal cut
    vertices is irreducible. This pass removes the ones it can; it does not claim zero.
    """
    current = list(placements)
    if not current or connected_component_count(current) != 1:
        return current

    for _ in range(max_iterations):
        cut = articulation_points(current)
        if not cut:
            break
        before_count = len(cut)
        cut_cols = sorted({(bp.x, bp.z) for bp in cut})
        applied: list[BrickPlacement] | None = None
        seen_pairs: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for col in cut_cols:
            cx, cz = col
            # z-neighbours only: a (1,2) z-bond is seam-neutral, so redundant bonding
            # can never disturb masonry seams (an x redundant bond would).
            for ncol in ((cx, cz + 1), (cx, cz - 1)):
                pair = (min(col, ncol), max(col, ncol))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                a, b = pair
                shared = _col_1x1_layers(current, a) & _col_1x1_layers(current, b)
                for layer in sorted(shared):
                    brick_a = _brick_at(current, a[0], layer, a[1])
                    brick_b = _brick_at(current, b[0], layer, b[1])
                    if brick_a is None or brick_b is None or brick_a is brick_b:
                        continue
                    new = [bp for bp in current if bp is not brick_a and bp is not brick_b]
                    new.append(_make_z_bond(a, b, layer, color_id))
                    if not _bond_guards_ok(current, new, require_merge=False):
                        continue
                    if len(articulation_points(new)) < before_count:
                        applied = new
                        break
                if applied is not None:
                    break
            if applied is not None:
                break
        if applied is None:
            break
        current = applied
    return current


def _merge_components_cap_fallback(
    placements: list[BrickPlacement], color_id: int, max_iterations: int = 50
) -> list[BrickPlacement]:
    """Graph-driven repair: bond disconnected components into ONE assembly.

    The structural fix v1's heuristic passes never achieved: a solid cube packs to
    4 components and a plus-star to 7 -- full-height 1x1 towers at corners/arm-tips
    that touch the spine only laterally and so share no stud across layers
    (correctly separate graph components). The repair:

      1. Compute the components and each column's top layer ONCE (from the input --
         never from caps, so anchor heights cannot run away).
      2. Build the component-adjacency graph (two components are adjacent when they
         own cardinally-adjacent columns) and a spanning tree rooted at the anchor
         (the component with the most ground bricks).
      3. For each tree edge, bond the two components with a 2x2 CAP brick placed one
         layer ABOVE the taller bonded column. The cap shares a stud with each
         column's top brick (a vertical edge to each), merging the two components.

    Caps sit ABOVE the build, so the existing layers -- and their masonry seams --
    are never disturbed; equal-height towers (cube, star, solid grids) need no
    column extension. Unequal columns are extended up to the cap with 1x1 bricks;
    cap overhang collisions are resolved by trying both overhang sides at each
    candidate layer, searching upward for the lowest free slot.

    A disconnected XZ footprint (genuinely separate objects with no cardinally-
    adjacent columns) correctly stays multi-component -- the spanning tree only
    reaches components reachable through adjacency.

    KNOWN TRADEOFF (Step 4 refines): caps above the build EXTEND its height. A
    hub column bonding several arms (e.g. the plus-star center bonding 4 arms)
    forces caps onto successive layers, so very fragmented or hub-heavy shapes can
    gain multiple cap layers. For solid-ish real ImageShaper volumes the fragment
    count is low and the overhead is small; Step 4's articulation-driven split/
    re-merge is the planned place to bond in-volume and remove this height cost.
    """
    base = list(placements)
    if not base or max(bp.y for bp in base) == 0:
        # A single flat layer has no vertical structure to bond -- every brick is
        # its own graph component, but stacking caps would wrongly turn a flat
        # build into a multi-layer one. Leave it flat (it sits on a baseplate).
        return base
    components = connected_components_list(base)
    if len(components) <= 1:
        return base

    key_to_comp: dict[_BrickKey, int] = {
        key: ci for ci, comp in enumerate(components) for key in comp
    }
    occupied: set[tuple[int, int, int]] = set()
    col_top: dict[tuple[int, int], int] = {}
    col_comps: dict[tuple[int, int], set[int]] = {}
    for bp in base:
        ci = key_to_comp[_brick_key(bp)]
        for sx, sz in _footprint(bp):
            occupied.add((sx, bp.y, sz))
            col_top[(sx, sz)] = max(col_top.get((sx, sz), -1), bp.y)
            col_comps.setdefault((sx, sz), set()).add(ci)

    # Component adjacency, with a representative (stud, neighbor) bond per pair.
    adjacency: dict[tuple[int, int], tuple[tuple[int, int], tuple[int, int]]] = {}
    neighbors: dict[int, set[int]] = {ci: set() for ci in range(len(components))}
    for (sx, sz), cas in col_comps.items():
        for nx_, nz_ in ((sx + 1, sz), (sx - 1, sz), (sx, sz + 1), (sx, sz - 1)):
            cbs = col_comps.get((nx_, nz_))
            if not cbs:
                continue
            for ca in cas:
                for cb in cbs:
                    if ca == cb:
                        continue
                    pair = (min(ca, cb), max(ca, cb))
                    neighbors[ca].add(cb)
                    if pair not in adjacency:
                        adjacency[pair] = ((sx, sz), (nx_, nz_))

    ground = [sum(1 for k in comp if k[1] == 0) for comp in components]
    anchor = max(range(len(components)), key=lambda i: (ground[i], len(components[i])))

    # Spanning tree (BFS) over the component-adjacency graph from the anchor.
    visited = {anchor}
    queue = [anchor]
    tree_edges: list[tuple[int, int]] = []
    while queue:
        u = queue.pop(0)
        for v in sorted(neighbors[u]):
            if v not in visited:
                visited.add(v)
                tree_edges.append((min(u, v), max(u, v)))
                queue.append(v)

    new_bricks: list[BrickPlacement] = []
    for pair in tree_edges:
        s, n = adjacency[pair]
        target = max(col_top[s], col_top[n])

        # Find the LOWEST layer (>= target+1) at which SOME 2x2 cap position is
        # collision-free, trying both overhang sides at each layer. Searching both
        # positions per layer (rather than bumping one position) guarantees the
        # chosen layer is genuinely free -- no cap is ever placed on an occupied
        # slot (which would later trip the duplicate-key guard in the graph).
        cap_layer = target + 1
        cap_pos: tuple[int, int] | None = None
        for candidate in range(target + 1, target + 1 + max_iterations):
            for cap_x, cap_z in _cap_positions(s, n):
                studs = [(cap_x + dx, candidate, cap_z + dz) for dx in (0, 1) for dz in (0, 1)]
                if not any(p in occupied for p in studs):
                    cap_layer, cap_pos = candidate, (cap_x, cap_z)
                    break
            if cap_pos is not None:
                break
        if cap_pos is None:
            # No free slot within the search window: skip this bond rather than
            # place a colliding cap. The component stays separate (surfaced by the
            # done-when 1-component test) -- never corrupts the placement list.
            continue

        # Extend each bonded column up to the cap base so the cap shares its stud.
        for cx, cz in (s, n):
            for yy in range(col_top[(cx, cz)] + 1, cap_layer):
                if (cx, yy, cz) not in occupied:
                    occupied.add((cx, yy, cz))
                    new_bricks.append(
                        BrickPlacement(BRICK_PART_IDS[(1, 1)], color_id, cx, yy, cz, 1, 1)
                    )

        cap_x, cap_z = cap_pos
        for dx in (0, 1):
            for dz in (0, 1):
                occupied.add((cap_x + dx, cap_layer, cap_z + dz))
        new_bricks.append(
            BrickPlacement(BRICK_PART_IDS[(2, 2)], color_id, cap_x, cap_layer, cap_z, 2, 2)
        )

    return base + new_bricks


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

    # MIN_GRID_DIM is the single source of truth for the minimum footprint (X/Z);
    # the Shaper seam's validate_grid enforces the same floor on its output.
    if X < MIN_GRID_DIM or Z < MIN_GRID_DIM:
        px = max(0, MIN_GRID_DIM - X)
        pz = max(0, MIN_GRID_DIM - Z)
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
                # No orientation expansion: every greedy brick is width-along-X,
                # length-along-Z. (BRICK_TYPES has only w<=l entries; the bond-only
                # (2,1) is constructed solely by _bond_components_in_volume and must
                # never enter the greedy fill, or it would rewrite the masonry seams.)
                for bw, bl in effective_brick_set:
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
                            continue  # try next (smaller) brick

                    # Accept
                    placements.append(candidate)
                    covered[x : x + bw, z : z + bl] = True
                    placed = True
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

    # Phase B/C repair pipeline. The v1 heuristic touch-ups run first, each of which
    # may ADD bricks; connectivity_repair guarantees 0 unsupported. Then the Step-4
    # in-volume bonder fuses the fragment towers into ONE component WITHOUT adding
    # height (bonds sit at existing layers), preserving the masonry seams (z-bonds
    # are seam-neutral; x-bonds are seam-gated). _eliminate_arm_tip_articulations
    # then hardens single-bond fragments into cycles where geometry allows. The
    # cap-above fallback only runs if some edge could not be bonded in-volume (rare;
    # never for solid/star grids). Surface tiles run last (footprint preserved).
    placements = _remove_isolated_pillars(placements)
    placements = _fill_central_hub(placements, grid, color_id)
    placements = connectivity_repair(placements)        # SUPPORT kernel: 0 unsupported
    placements = _add_floor_support(placements, color_id)
    placements = _brace_thin_columns(placements, color_id)
    placements = _bond_components_in_volume(placements, color_id)  # -> 1 component, no height
    placements = _eliminate_arm_tip_articulations(placements, color_id)  # harden cut vertices
    if connected_component_count(placements) > 1:
        placements = _merge_components_cap_fallback(placements, color_id)  # deferred edges only
    return _apply_surface_tiles(placements)

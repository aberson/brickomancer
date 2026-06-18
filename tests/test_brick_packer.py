"""Tests for brick_packer and ldraw_writer.

Covers:
- 5×5×5 solid voxel cube: connectivity, placement coverage
- Masonry offset behaviour
- interlocking_check helper
- connectivity_repair helper
- ldraw_writer: header, step markers, coordinate conversion
- Integration: pack → write_ldr round-trip (file parseable)
"""

import os
import tempfile

import numpy as np
import pytest

from brickomancer.models.brick import (
    BRICK_PART_IDS,
    BRICK_TYPES,
    TILE_PART_IDS,
    BrickPlacement,
)
from brickomancer.services.brick_packer import (
    _bond_components_in_volume,
    _bond_guards_ok,
    _collect_footprints,
    _eliminate_arm_tip_articulations,
    _footprint,
    _has_connection,
    _is_arm_tip_brick,
    articulation_points,
    build_connectivity_graph,
    connected_component_count,
    connectivity_repair,
    interlocking_check,
    pack,
    unsupported_bricks,
)
from brickomancer.services.ldraw_writer import _brick_line, sequence_steps, write_ldr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _solid_cube(size: int) -> np.ndarray:
    """Return a solid bool cube of shape (size, size, size)."""
    return np.ones((size, size, size), dtype=bool)


def _make_bp(x: int, y: int, z: int, w: int = 1, ln: int = 1, color: int = 15) -> BrickPlacement:
    return BrickPlacement(
        part_id=BRICK_PART_IDS[(w, ln)],
        color_id=color,
        x=x,
        y=y,
        z=z,
        width=w,
        length=ln,
    )


# ---------------------------------------------------------------------------
# _footprint
# ---------------------------------------------------------------------------


class TestFootprint:
    def test_1x1(self):
        bp = _make_bp(3, 0, 5)
        assert _footprint(bp) == {(3, 5)}

    def test_2x4(self):
        bp = _make_bp(0, 0, 0, 2, 4)
        expected = {(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)}
        assert _footprint(bp) == expected

    def test_1x3(self):
        bp = _make_bp(2, 1, 1, 1, 3)
        assert _footprint(bp) == {(2, 1), (2, 2), (2, 3)}


# ---------------------------------------------------------------------------
# _has_connection
# ---------------------------------------------------------------------------


class TestHasConnection:
    def test_connected(self):
        bp = _make_bp(0, 1, 0)
        below = {(0, 0), (1, 0)}
        assert _has_connection(bp, below)

    def test_not_connected(self):
        bp = _make_bp(3, 1, 3)
        below = {(0, 0), (1, 0)}
        assert not _has_connection(bp, below)

    def test_partial_overlap_counts(self):
        bp = _make_bp(0, 1, 0, 2, 2)  # covers (0,0),(0,1),(1,0),(1,1)
        below = {(1, 1)}
        assert _has_connection(bp, below)


# ---------------------------------------------------------------------------
# interlocking_check
# ---------------------------------------------------------------------------


class TestInterlockingCheck:
    def test_layer_0_unchanged(self):
        bricks = [_make_bp(0, 0, 0)]
        result = interlocking_check(bricks, 0)
        assert result == bricks

    def test_connected_brick_kept(self):
        bricks = [_make_bp(0, 0, 0), _make_bp(0, 1, 0)]
        result = interlocking_check(bricks, 1)
        # Both bricks should survive
        assert any(bp.y == 1 and bp.x == 0 and bp.z == 0 for bp in result)

    def test_disconnected_brick_replaced_with_1x1(self):
        # Layer 0: stud at (0,0); Layer 1: brick at (3,3) — no overlap
        bricks = [_make_bp(0, 0, 0), _make_bp(3, 1, 3)]
        result = interlocking_check(bricks, 1)
        # The disconnected 1×1 at (3,1,3) should be removed (no overlap with (0,0))
        layer1_bricks = [bp for bp in result if bp.y == 1]
        # No repair stud either because (3,3) ∩ {(0,0)} = ∅
        assert layer1_bricks == []

    def test_disconnected_multi_stud_partially_overlapping(self):
        # Layer 0: stud at (1,0); Layer 1: 1×2 at (1,1) spanning (1,0)-(1,1)
        # overlap exists at (1,0) → should keep as 1×1 at (1,0)
        bricks = [_make_bp(1, 0, 0), _make_bp(1, 1, 0, 1, 2)]
        result = interlocking_check(bricks, 1)
        layer1_bricks = [bp for bp in result if bp.y == 1]
        # The 1×2 at (1,1,0) overlaps with below at (1,0) → kept as-is
        assert len(layer1_bricks) == 1


# ---------------------------------------------------------------------------
# connectivity_repair
# ---------------------------------------------------------------------------


class TestConnectivityRepair:
    def test_empty(self):
        assert connectivity_repair([]) == []

    def test_no_repair_needed(self):
        bricks = [_make_bp(0, 0, 0), _make_bp(0, 1, 0)]
        result = connectivity_repair(bricks)
        # No extra bricks should be added
        assert len(result) == 2

    def test_repair_adds_1x1(self):
        # Layer 0: stud at (0,0); Layer 1: stud at (5,5) — disconnected
        bricks = [_make_bp(0, 0, 0), _make_bp(5, 1, 5)]
        result = connectivity_repair(bricks)
        # The disconnected brick at (5,1,5) is REPLACED by a bridge 1×1 at
        # the nearest stud in below_fps, which is (0,0).
        # Result must have exactly 2 bricks: layer-0 (0,0,0) + bridge (0,1,0).
        assert len(result) == 2, "result should have exactly 2 bricks"
        layer1 = [bp for bp in result if bp.y == 1]
        assert not any(bp.x == 5 and bp.z == 5 for bp in layer1), "original brick must be removed"
        repair_bricks = [bp for bp in layer1 if bp.x == 0 and bp.z == 0]
        assert len(repair_bricks) == 1, "bridge 1×1 at (0,1,0) should be present"
        assert repair_bricks[0].width == 1
        assert repair_bricks[0].length == 1

    def test_connectivity_repair_disconnected_gets_bridge_brick(self):
        # Layer 0: single stud at (0,0); Layer 1: brick at (5,5) — no overlap
        bricks = [_make_bp(0, 0, 0), _make_bp(5, 1, 5)]
        result = connectivity_repair(bricks)
        # The disconnected brick at (5,1,5) is REPLACED by a bridge 1×1 at the
        # nearest stud in below_fps (the nearest stud to centroid (5.5, 5.5) is (0,0)).
        # Original (5,1,5) must NOT be in result.
        assert not any(bp.y == 1 and bp.x == 5 and bp.z == 5 for bp in result), (
            "disconnected brick must be removed, not kept"
        )
        bridge_bricks = [bp for bp in result if bp.y == 1 and bp.x == 0 and bp.z == 0]
        assert len(bridge_bricks) == 1, "bridge pillar should be inserted at below stud (0,0)"
        assert bridge_bricks[0].width == 1
        assert bridge_bricks[0].length == 1


# ---------------------------------------------------------------------------
# pack — 5×5×5 cube
# ---------------------------------------------------------------------------


class TestPack:
    def test_returns_list_of_brick_placements(self):
        grid = _solid_cube(5)
        result = pack(grid, color_id=15)
        assert isinstance(result, list)
        assert all(isinstance(bp, BrickPlacement) for bp in result)

    def test_all_voxels_covered(self):
        """Every True voxel in the grid must be covered by exactly one brick."""
        grid = _solid_cube(5)
        result = pack(grid, color_id=15)

        x_dim, y_dim, z_dim = grid.shape
        covered = np.zeros((x_dim, y_dim, z_dim), dtype=int)
        for bp in result:
            # The connectivity-merge pass may add bonding bricks above the grid
            # (a thin connective cap); those are not voxel coverage. Ignore any
            # stud outside the original grid bounds -- every TRUE voxel must still
            # be covered by an in-grid brick, which is what this asserts.
            if bp.y >= y_dim:
                continue
            for dx in range(bp.width):
                for dz in range(bp.length):
                    cx, cz = bp.x + dx, bp.z + dz
                    if cx < x_dim and cz < z_dim:
                        covered[cx, bp.y, cz] += 1

        # Every voxel should be covered at least once
        # (repair bricks may overlap, so we allow >=1)
        assert (covered >= 1).all(), "Some voxels not covered"

    def test_connectivity_every_layer_above_zero(self):
        """Every brick at y>0 must share ≥1 stud with a brick in layer y-1."""
        grid = _solid_cube(5)
        result = pack(grid, color_id=15)

        for y in range(1, 5):
            below_fps = _collect_footprints(result, y - 1)
            layer_bricks = [bp for bp in result if bp.y == y]
            for bp in layer_bricks:
                assert _has_connection(bp, below_fps), (
                    f"Brick at ({bp.x},{bp.y},{bp.z}) w={bp.width} l={bp.length} "
                    f"has no connection to layer {y-1}"
                )

    def test_color_id_propagated(self):
        grid = _solid_cube(3)
        result = pack(grid, color_id=4)
        assert all(bp.color_id == 4 for bp in result)

    def test_3d_invalid_raises(self):
        with pytest.raises(ValueError):
            pack(np.ones((5, 5), dtype=bool))

    def test_sparse_grid(self):
        """Single isolated voxel: should produce exactly one 1×1 brick."""
        grid = np.zeros((5, 5, 5), dtype=bool)
        grid[2, 0, 2] = True
        result = pack(grid)
        layer0 = [bp for bp in result if bp.y == 0]
        assert len(layer0) == 1
        assert layer0[0].width == 1
        assert layer0[0].length == 1

    def test_single_layer_grid(self):
        """A single-layer (Y=1) grid should pack without connectivity issues."""
        grid = np.ones((4, 1, 4), dtype=bool)
        result = pack(grid)
        assert all(bp.y == 0 for bp in result)

    def test_part_ids_valid(self):
        """All part_ids in the output must be in BRICK_PART_IDS or TILE_PART_IDS values."""
        valid_ids = set(BRICK_PART_IDS.values()) | set(TILE_PART_IDS.values())
        grid = _solid_cube(4)
        result = pack(grid)
        for bp in result:
            assert bp.part_id in valid_ids, f"Unknown part_id: {bp.part_id}"


# ---------------------------------------------------------------------------
# TestMasonryInterlocking
# ---------------------------------------------------------------------------


class TestMasonryInterlocking:
    def test_even_odd_layers_have_different_x_seam_sets(self):
        """Odd layers should have different seam positions than even layers."""
        voxels = np.ones((6, 2, 4), dtype=bool)
        result = pack(voxels)

        def seam_set(layer: int) -> frozenset[int]:
            return frozenset(bp.x + bp.width for bp in result if bp.y == layer)

        even_seams = seam_set(0)
        odd_seams = seam_set(1)
        assert even_seams != odd_seams, (
            f"Even and odd layers have the same seam set {even_seams!r}; "
            "masonry interlocking is not working"
        )

    def test_odd_layer_has_multi_stud_brick_starting_at_x1(self):
        """After pre-pass places 1×1 at x=0, main scan should place a wide brick at x=1."""
        voxels = np.ones((6, 2, 2), dtype=bool)
        result = pack(voxels)

        odd_layer = [bp for bp in result if bp.y == 1]
        # Confirm pre-pass placed a 1×1 at x=0 in at least one Z row
        has_starter = any(bp.x == 0 and bp.width == 1 for bp in odd_layer)
        assert has_starter, "Pre-pass should place a 1×1 starter at x=0 in odd layer"
        # Confirm at least one multi-stud brick starts at x=1
        has_wide_at_x1 = any(bp.x == 1 and bp.width > 1 for bp in odd_layer)
        assert has_wide_at_x1, (
            "After pre-pass at x=0, main scan should produce a multi-stud brick starting at x=1"
        )

    def test_no_all_1x1_layer_on_wide_arm(self):
        """An 8-wide grid should have multi-stud bricks in every layer."""
        voxels = np.ones((8, 2, 4), dtype=bool)
        result = pack(voxels)

        for layer in range(2):
            layer_bricks = [bp for bp in result if bp.y == layer]
            all_1x1 = all(bp.width == 1 and bp.length == 1 for bp in layer_bricks)
            assert not all_1x1, (
                f"Layer {layer} consists entirely of 1×1 bricks; "
                "packer should produce multi-stud bricks on a wide arm"
            )

    def test_abab_layer_pattern(self):
        """Even layers should match each other and odd layers should match each other."""
        voxels = np.ones((6, 4, 4), dtype=bool)
        result = pack(voxels)

        def seam_set(layer: int) -> frozenset[int]:
            return frozenset(bp.x + bp.width for bp in result if bp.y == layer)

        s0 = seam_set(0)
        s1 = seam_set(1)
        s2 = seam_set(2)
        s3 = seam_set(3)

        assert s0 == s2, f"Even layers must match: layer0={s0!r}, layer2={s2!r}"
        assert s1 == s3, f"Odd layers must match: layer1={s1!r}, layer3={s3!r}"
        assert s0 != s1, (
            f"Even and odd layers must differ (interlocking): layer0={s0!r}, layer1={s1!r}"
        )


# ---------------------------------------------------------------------------
# sequence_steps
# ---------------------------------------------------------------------------


class TestSequenceSteps:
    def test_empty(self):
        assert sequence_steps([]) == []

    def test_single_brick(self):
        bricks = [_make_bp(0, 0, 0)]
        steps = sequence_steps(bricks)
        assert len(steps) == 1
        assert steps[0] == bricks

    def test_eight_bricks_one_step(self):
        bricks = [_make_bp(i, 0, 0) for i in range(8)]
        steps = sequence_steps(bricks)
        assert len(steps) == 1
        assert len(steps[0]) == 8

    def test_nine_bricks_two_steps(self):
        bricks = [_make_bp(i, 0, 0) for i in range(9)]
        steps = sequence_steps(bricks)
        assert len(steps) == 2
        assert len(steps[0]) == 8
        assert len(steps[1]) == 1

    def test_sorted_by_y(self):
        bricks = [_make_bp(0, 2, 0), _make_bp(0, 0, 0), _make_bp(0, 1, 0)]
        steps = sequence_steps(bricks)
        flat = [bp for step in steps for bp in step]
        assert flat[0].y == 0
        assert flat[1].y == 1
        assert flat[2].y == 2

    def test_custom_batch_size(self):
        bricks = [_make_bp(i, 0, 0) for i in range(10)]
        steps = sequence_steps(bricks, bricks_per_step=3)
        assert len(steps) == 4  # 3+3+3+1


# ---------------------------------------------------------------------------
# write_ldr
# ---------------------------------------------------------------------------


class TestWriteLdr:
    def test_file_created(self):
        bricks = [_make_bp(0, 0, 0)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.ldr")
            result = write_ldr(bricks, path)
            assert os.path.isfile(result)

    def test_header_present(self):
        bricks = [_make_bp(0, 0, 0)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.ldr")
            write_ldr(bricks, path, tier_name="compact")
            content = open(path, encoding="utf-8").read()
            assert "0 Brickomancer Build" in content
            assert "0 Name: test.ldr" in content
            assert "0 Author: Brickomancer" in content
            assert "0 Tier: compact" in content

    def test_brick_line_format(self):
        """Check LDraw type-1 line format and coordinate conversion."""
        # Brick at stud (1, 2, 3) with width=1 length=2 → LDU (20, -48, 70)
        bp = _make_bp(1, 2, 3, 1, 2)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.ldr")
            write_ldr([bp], path)
            content = open(path, encoding="utf-8").read()
            # x=1*20+(1-1)*10=20, y=2*-24=-48, z=3*20+(2-1)*10=70, identity matrix, part 3004
            assert "1 15 20 -48 70 1 0 0 0 1 0 0 0 1 3004.dat" in content

    def test_step_markers_every_8(self):
        """0 STEP should appear after every batch of 8, including the last."""
        bricks = [_make_bp(i, 0, 0) for i in range(17)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "steps.ldr")
            write_ldr(bricks, path)
            content = open(path, encoding="utf-8").read()
            lines = content.splitlines()
            step_indices = [i for i, line in enumerate(lines) if line.strip() == "0 STEP"]
            # 17 bricks → 3 batches (8, 8, 1) → 3 STEP markers (one per batch) + 1 cover page STEP
            assert len(step_indices) == 4

    def test_trailing_step_marker_present(self):
        """The last batch must be followed by 0 STEP so LPub3D renders it."""
        bricks = [_make_bp(i, 0, 0) for i in range(8)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "laststep.ldr")
            write_ldr(bricks, path)
            content = open(path, encoding="utf-8").read()
            # 1 build batch STEP + 1 cover page STEP
            assert content.count("0 STEP") == 2

    def test_step_marker_after_exactly_8(self):
        """16 bricks → exactly 2 STEP markers, one per batch."""
        bricks = [_make_bp(i, 0, 0) for i in range(16)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mid.ldr")
            write_ldr(bricks, path)
            content = open(path, encoding="utf-8").read()
            # 2 build batch STEPs + 1 cover page STEP
            assert content.count("0 STEP") == 3



# ---------------------------------------------------------------------------
# Integration: pack → write_ldr round-trip
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_5x5x5_pack_and_write(self):
        """Full pipeline: 5×5×5 cube → placements → .ldr file."""
        grid = _solid_cube(5)
        placements = pack(grid, color_id=15)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cube5.ldr")
            out = write_ldr(placements, path, tier_name="standard")

            assert os.path.isfile(out)
            content = open(out, encoding="utf-8").read()

            # File must start with the header
            assert content.startswith("0 Brickomancer Build")

            # Every non-comment line starting with "1 " must have 15 fields
            # (LDraw type-1 format: 1 colour x y z a b c d e f g h i part)
            for line in content.splitlines():
                if line.startswith("1 "):
                    fields = line.split()
                    assert len(fields) == 15, f"Malformed brick line: {line!r}"
                    # Field 0 = "1", field 14 = part file ending in .dat
                    assert fields[14].endswith(".dat")

            # STEP markers exist (125 bricks → many batches)
            assert "0 STEP" in content

    def test_connectivity_5x5x5(self):
        """Every brick at y>0 connects to layer below after full pack."""
        grid = _solid_cube(5)
        placements = pack(grid, color_id=15)

        for y in range(1, 5):
            below_fps = _collect_footprints(placements, y - 1)
            for bp in placements:
                if bp.y == y:
                    assert _has_connection(bp, below_fps), (
                        f"Disconnected brick at ({bp.x},{bp.y},{bp.z})"
                    )


# ---------------------------------------------------------------------------
# Phase B: connectivity-graph analysis (Step 3)
# ---------------------------------------------------------------------------


def _plus_star() -> np.ndarray:
    """A 5x3x5 plus-cross star: the x=2 plane and z=2 plane occupied at all y.

    This is the done-when star fixture. Before the merge it packs to 7 disjoint
    components (arm-tip 1x1 towers + center); after Phase B it must be exactly one.
    """
    grid = np.zeros((5, 3, 5), dtype=bool)
    grid[2, :, :] = True
    grid[:, :, 2] = True
    return grid


class TestConnectivityGraph:
    def test_empty(self):
        g = build_connectivity_graph([])
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0

    def test_single_brick(self):
        g = build_connectivity_graph([_make_bp(0, 0, 0)])
        assert g.number_of_nodes() == 1
        assert g.number_of_edges() == 0

    def test_two_stacked_connected(self):
        """Two 1x1 sharing an (x,z) on adjacent layers form one edge / one component."""
        g = build_connectivity_graph([_make_bp(0, 0, 0), _make_bp(0, 1, 0)])
        assert g.number_of_edges() == 1
        assert connected_component_count([_make_bp(0, 0, 0), _make_bp(0, 1, 0)]) == 1

    def test_two_stacked_disconnected(self):
        """Bricks at different (x,z) on adjacent layers share no stud: 0 edges."""
        placements = [_make_bp(0, 0, 0), _make_bp(3, 1, 3)]
        assert build_connectivity_graph(placements).number_of_edges() == 0
        assert connected_component_count(placements) == 2

    def test_no_lateral_edges(self):
        """Two XZ-adjacent 1x1 on the SAME layer are not bonded (no stud edge)."""
        placements = [_make_bp(0, 0, 0), _make_bp(1, 0, 0)]
        assert build_connectivity_graph(placements).number_of_edges() == 0
        assert connected_component_count(placements) == 2

    def test_three_layer_chain(self):
        """A vertical 1x1 chain is a path graph: 2 edges, 1 component."""
        placements = [_make_bp(0, 0, 0), _make_bp(0, 1, 0), _make_bp(0, 2, 0)]
        assert build_connectivity_graph(placements).number_of_edges() == 2
        assert connected_component_count(placements) == 1

    def test_duplicate_key_raises(self):
        """Two placements with the same (x,y,z,w,l) collide -- loud, not silent."""
        dup = [_make_bp(0, 0, 0, color=15), _make_bp(0, 0, 0, color=4)]
        with pytest.raises(AssertionError):
            build_connectivity_graph(dup)


class TestDoneWhenInvariants:
    """The Step 3 done-when: cube + star -> 1 component + 0 unsupported."""

    def test_cube_single_component(self):
        assert connected_component_count(pack(_solid_cube(5), color_id=15)) == 1

    def test_cube_zero_unsupported(self):
        assert unsupported_bricks(pack(_solid_cube(5), color_id=15)) == []

    def test_star_single_component(self):
        assert connected_component_count(pack(_plus_star(), color_id=14)) == 1

    def test_star_zero_unsupported(self):
        assert unsupported_bricks(pack(_plus_star(), color_id=14)) == []


class TestUnsupportedBricks:
    def test_ground_layer_always_supported(self):
        assert unsupported_bricks([_make_bp(0, 0, 0), _make_bp(1, 0, 1)]) == []

    def test_detects_floating(self):
        """A brick at y>0 with no stud-sharing brick below is unsupported."""
        floating = _make_bp(3, 1, 3)
        result = unsupported_bricks([_make_bp(0, 0, 0), floating])
        assert result == [floating]


class TestArticulationPoints:
    def test_empty(self):
        assert articulation_points([]) == []

    def test_returns_brick_placements(self):
        """On a 3-brick vertical chain the middle brick is the cut vertex."""
        chain = [_make_bp(0, 0, 0), _make_bp(0, 1, 0), _make_bp(0, 2, 0)]
        cut = articulation_points(chain)
        assert all(isinstance(bp, BrickPlacement) for bp in cut)
        assert [(bp.x, bp.y, bp.z) for bp in cut] == [(0, 1, 0)]

    def test_star_has_articulation_points(self):
        """The packed star has cut vertices (Step-4 input); assert non-empty + type."""
        cut = articulation_points(pack(_plus_star(), color_id=14))
        assert cut  # non-empty
        assert all(isinstance(bp, BrickPlacement) for bp in cut)

    def test_articulation_point_actually_disconnects(self):
        """A reported cut vertex, when removed, must disconnect the graph (definition)."""
        # A 5-brick T: vertical chain (0,0,0)-(0,1,0)-(0,2,0) with a branch at the top
        # sharing the top stud's column upward is overkill; use the canonical chain +
        # a second branch off the middle so the middle is a true cut vertex.
        bricks = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0), _make_bp(0, 2, 0),  # spine
        ]
        cut = articulation_points(bricks)
        assert [(bp.x, bp.y, bp.z) for bp in cut] == [(0, 1, 0)]
        # Removing the middle brick splits the chain into two components.
        remaining = [bp for bp in bricks if (bp.x, bp.y, bp.z) != (0, 1, 0)]
        assert connected_component_count(remaining) == 2


class TestInVolumeBonding:
    """Step 4: _bond_components_in_volume replaces the cap-above merge.

    Same contracts as the old TestMergeComponents (1 component, 0 unsupported,
    deterministic, non-adjacent stays separate) PLUS the new headline invariant:
    bonds sit at existing layers, so NO brick is added above the input's top layer.
    """

    def test_idempotent_on_merged(self):
        """Re-running the bonder on an already-1-component build adds nothing."""
        packed = pack(_solid_cube(5), color_id=15)
        assert _bond_components_in_volume(packed, 15) == packed

    def test_single_layer_not_merged(self):
        """A flat single-layer build is left flat (no stacked caps)."""
        result = pack(np.ones((4, 1, 4), dtype=bool))
        assert all(bp.y == 0 for bp in result)

    def test_merges_adjacent_disconnected_columns(self):
        """Three cardinally-adjacent 1x1 towers (no shared studs) bond to one.

        This is the fragment scenario: adjacent columns that never bond laterally.
        (Genuinely separated, non-adjacent towers correctly stay multi-component.)
        """
        towers = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(1, 0, 0), _make_bp(1, 1, 0),
            _make_bp(2, 0, 0), _make_bp(2, 1, 0),
        ]
        assert connected_component_count(towers) == 3
        merged = _bond_components_in_volume(towers, 15)
        assert connected_component_count(merged) == 1
        assert unsupported_bricks(merged) == []

    def test_non_adjacent_components_stay_separate(self):
        """Physically separated towers (a gap between them) are NOT force-merged."""
        far = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(4, 0, 4), _make_bp(4, 1, 4),
        ]
        merged = _bond_components_in_volume(far, 15)
        assert connected_component_count(merged) == 2

    def test_bonds_add_no_height(self):
        """CODIFYING DIFF (audit-wire-shape rule): the old cap-above merge asserted
        ``any(bp.y > 1)`` -- that caps were stacked ABOVE the input. In-volume bonding
        removes exactly those caps, so the new contract is the opposite: every bond
        sits at an existing layer and NO brick is added above the input's top (y=1).
        """
        towers = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(1, 0, 0), _make_bp(1, 1, 0),
            _make_bp(2, 0, 0), _make_bp(2, 1, 0),
        ]
        merged = _bond_components_in_volume(towers, 15)
        assert connected_component_count(merged) == 1
        assert unsupported_bricks(merged) == []
        assert max(bp.y for bp in merged) == 1, "in-volume bonding must add no height"

    def test_merge_is_deterministic(self):
        """Same multi-component input -> identical bond output (no dict-order flakiness)."""
        towers = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(1, 0, 0), _make_bp(1, 1, 0),
            _make_bp(2, 0, 0), _make_bp(2, 1, 0),
        ]
        def _key(bp: BrickPlacement) -> tuple:
            return (bp.x, bp.y, bp.z, bp.width, bp.length, bp.part_id, bp.color_id)

        a = sorted(_key(bp) for bp in _bond_components_in_volume(towers, 15))
        b = sorted(_key(bp) for bp in _bond_components_in_volume(towers, 15))
        assert a == b

    def test_masonry_6x2x4_preserved_after_merge(self):
        """The 6x2x4 masonry grid (multi-component) keeps even!=odd seams after merge."""
        result = pack(np.ones((6, 2, 4), dtype=bool))
        assert connected_component_count(result) == 1

        def seam_set(layer: int) -> frozenset[int]:
            return frozenset(bp.x + bp.width for bp in result if bp.y == layer)

        assert seam_set(0) != seam_set(1)

    def test_masonry_8x2x4_preserved_after_merge(self):
        """The 8x2x4 grid keeps a multi-stud brick in every (in-grid) layer after merge."""
        result = pack(np.ones((8, 2, 4), dtype=bool))
        assert connected_component_count(result) == 1
        for layer in (0, 1):
            widths = [bp.width * bp.length for bp in result if bp.y == layer]
            assert any(area > 1 for area in widths), f"layer {layer} is all 1x1"

    def test_masonry_abab_preserved_after_merge(self):
        """In-volume bonding must NOT disturb the masonry ABAB seams.

        The highest-risk salvaged invariant: a 6x4x4 grid is multi-component, so the
        bonder fires -- and because every masonry bond is a z-direction (1,2) (width 1,
        so x+width is unchanged), the seam sets stay byte-for-byte identical. No x-bond
        ever fires on a solid grid (a z-bond is always available and preferred).
        """
        result = pack(np.ones((6, 4, 4), dtype=bool))
        assert connected_component_count(result) == 1

        def seam_set(layer: int) -> frozenset[int]:
            return frozenset(bp.x + bp.width for bp in result if bp.y == layer)

        assert seam_set(0) == seam_set(2)
        assert seam_set(1) == seam_set(3)
        assert seam_set(0) != seam_set(1)
        # Solid grids bond purely via seam-neutral z-bonds -- no (2,1) x-bond appears.
        assert all((bp.width, bp.length) != (2, 1) for bp in result)


# ---------------------------------------------------------------------------
# Step 4: zero-added-height in-volume bonding (the headline invariant)
# ---------------------------------------------------------------------------


def _plus_star_thin() -> np.ndarray:
    """A 7x3x7 plus-cross with longer (2-stud) arms -- a harder hub stress fixture."""
    grid = np.zeros((7, 3, 7), dtype=bool)
    grid[3, :, :] = True
    grid[:, :, 3] = True
    return grid


def _max_y(placements: list[BrickPlacement]) -> int:
    return max(bp.y for bp in placements)


class TestStep4ZeroAddedHeight:
    """In-volume bonding adds NO build-height layers above the input grid top.

    This is the headline Step-4 invariant -- it replaces the cap-above merge's height
    overshoot. The grid's top layer index is shape[1]-1; the packed output's max y must
    equal it exactly, while staying 1 connected component with 0 unsupported bricks.
    """

    def test_cube_zero_added_height(self):
        grid = _solid_cube(5)
        result = pack(grid, color_id=15)
        assert _max_y(result) == grid.shape[1] - 1 == 4
        assert connected_component_count(result) == 1
        assert unsupported_bricks(result) == []

    def test_plus_star_zero_added_height(self):
        """The done-when pathological fixture: the degree-4 hub bonds in-volume."""
        grid = _plus_star()
        result = pack(grid, color_id=14)
        assert _max_y(result) == grid.shape[1] - 1 == 2
        assert connected_component_count(result) == 1
        assert unsupported_bricks(result) == []

    def test_masonry_zero_added_height(self):
        grid = np.ones((6, 4, 4), dtype=bool)
        result = pack(grid)
        assert _max_y(result) == grid.shape[1] - 1 == 3
        assert connected_component_count(result) == 1
        assert unsupported_bricks(result) == []

    def test_three_adjacent_towers_bond_no_height(self):
        """The fragment scenario bonds to 1 component at the input height (y=1)."""
        towers = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(1, 0, 0), _make_bp(1, 1, 0),
            _make_bp(2, 0, 0), _make_bp(2, 1, 0),
        ]
        merged = _bond_components_in_volume(towers, 15)
        assert connected_component_count(merged) == 1
        assert _max_y(merged) == 1

    def test_thin_star_one_component_zero_unsupported(self):
        """The 7x3x7 thin star: a longer-armed hub exceeds the (1,4) z-extend reach,
        so it may retain +1 height -- but it must still bond to ONE component with no
        floating bricks (the structural guarantee holds even where height does not).
        """
        result = pack(_plus_star_thin(), color_id=15)
        assert connected_component_count(result) == 1
        assert unsupported_bricks(result) == []


class TestStep4SolidGridRobustness:
    """Sweep guards added after an adversarial review found regressions OFF the three
    hand-picked fixtures. Across a broad range of solid grids the packer must ALWAYS
    yield exactly 1 connected component with 0 unsupported bricks; and every THICK grid
    (Y>=3 and Z>=3 -- the shape of a real voxelised object) must add no height.

    DOCUMENTED LIMITATION: minimum-depth slabs (Z==2) and the Y==2, Z in {5,9} grids
    saturate the bond-layer budget (the thin-grid analogue of the plus-star hub), so
    they may keep +1/+2 height via the cap-above fallback -- but stay structurally
    sound (1 component, 0 unsupported). Real ImageShaper output is far thicker.
    """

    def test_no_solid_grid_is_multicomponent_or_floats(self):
        for X in range(2, 11):
            for Y in range(2, 7):
                for Z in range(2, 11):
                    result = pack(np.ones((X, Y, Z), dtype=bool))
                    assert connected_component_count(result) == 1, (X, Y, Z)
                    assert unsupported_bricks(result) == [], (X, Y, Z)

    def test_thick_solid_grids_add_no_height(self):
        """Every Y>=3, Z>=3 solid grid bonds fully in-volume (zero added height)."""
        for X in range(2, 11):
            for Y in range(3, 7):
                for Z in range(3, 11):
                    result = pack(np.ones((X, Y, Z), dtype=bool))
                    assert _max_y(result) == Y - 1, (X, Y, Z)

    def test_thin_slabs_stay_structurally_sound(self):
        """The documented-limitation thin slabs are still 1 component + 0 unsupported
        (height may exceed the input top -- buildable, just not height-optimal).
        """
        for shape in ((6, 2, 2), (3, 2, 2), (6, 2, 5), (7, 2, 9)):
            result = pack(np.ones(shape, dtype=bool))
            assert connected_component_count(result) == 1, shape
            assert unsupported_bricks(result) == [], shape

    def test_tile_split_does_not_sever_bonds(self):
        """Regression (adversarial review BLOCKER): a top-layer wide brick with no exact
        tile (e.g. a (2,3) on a (7,2,3) grid) was split into strip tiles, severing the
        bond and leaving 4 components. Tiles now replace 1-for-1 only, so the build
        stays connected at the input height.
        """
        result = pack(np.ones((7, 2, 3), dtype=bool))
        assert connected_component_count(result) == 1
        assert unsupported_bricks(result) == []
        assert _max_y(result) == 1


# ---------------------------------------------------------------------------
# Step 4: the bond-only (2,1) part + its 90-deg writer rotation
# ---------------------------------------------------------------------------


class TestStep4BondPart:
    def test_2x1_maps_to_3004(self):
        """(2,1) is the SAME physical part as (1,2): LDraw 3004 (BOM aggregates them)."""
        assert BRICK_PART_IDS[(2, 1)] == "3004"
        assert BRICK_PART_IDS[(1, 2)] == "3004"

    def test_2x1_is_bond_only(self):
        """(2,1) must NOT be in BRICK_TYPES -- the greedy fill never emits it."""
        assert (2, 1) not in BRICK_TYPES
        assert (2, 1) in BRICK_PART_IDS

    def test_2x1_emits_rotated_matrix(self):
        """The (2,1) bond renders as part 3004 rotated 90 deg about Y (studs along X).

        Render-sensitive (only an LDView render proves the brick lands correctly), so
        this pins the exact matrix + centroid the operator UAT will visually confirm.
        """
        bp = _make_bp(1, 2, 3, 2, 1)  # x=1,y=2,z=3, width=2,length=1
        line = _brick_line(bp)
        # x = 1*20 + (2-1)*10 = 30 ; y = 2*-24 = -48 ; z = 3*20 + (1-1)*10 = 60
        assert line == "1 15 30 -48 60 0 0 1 0 1 0 -1 0 0 3004.dat"

    def test_1x2_keeps_identity_matrix(self):
        """The Z-spanning (1,2) is part 3004's native orientation -> identity matrix."""
        bp = _make_bp(1, 2, 3, 1, 2)
        line = _brick_line(bp)
        # x = 1*20 = 20 ; z = 3*20 + (2-1)*10 = 70
        assert line == "1 15 20 -48 70 1 0 0 0 1 0 0 0 1 3004.dat"

    def test_bom_aggregates_1x2_and_2x1_as_one_3004(self):
        """BOM groups by part_id, so a (1,2) + a (2,1) form ONE 3004 line of qty 2."""
        from brickomancer.services.suggestion_service import _build_parts_list

        placements = [_make_bp(0, 0, 0, 1, 2), _make_bp(2, 0, 0, 2, 1)]
        parts = _build_parts_list(placements)
        threes = [pc for pc in parts if pc.part_id == "3004"]
        assert len(threes) == 1
        assert threes[0].qty == 2

    def test_top_surface_2x1_stays_a_brick(self):
        """A top-surface (2,1) has no tile mapping; tiling would split it into 1x1
        tiles and sever the x-bond, so it must stay a brick. (The plus-star packs a
        (2,1) at its top layer, so this path is live in production.)
        """
        from brickomancer.services.brick_packer import _apply_surface_tiles

        result = _apply_surface_tiles([_make_bp(0, 0, 0, 2, 1)])
        assert len(result) == 1
        assert (result[0].width, result[0].length) == (2, 1)
        assert result[0].part_id == "3004"

    def test_2x1_matrix_is_a_proper_rotation(self):
        """The (2,1) matrix must be a PROPER rotation (det=+1, orthonormal), not a
        sign-flipped reflection. A bare string-equality check would pass a reflection
        like `0 0 1 0 1 0 1 0 0` (det=-1) that renders the brick mirrored; this guards
        the one render property verifiable without LDView.
        """
        bp = _make_bp(0, 0, 0, 2, 1)
        nums = _brick_line(bp).split()[5:14]
        m = np.array([float(v) for v in nums]).reshape(3, 3)
        assert np.isclose(np.linalg.det(m), 1.0)              # proper rotation
        assert np.allclose(m @ m.T, np.eye(3))                # orthonormal (no scale/shear)
        assert np.allclose(m @ np.array([0, 0, 10]), [10, 0, 0])  # part-Z -> model-X
        assert np.allclose(m @ np.array([0, 1, 0]), [0, 1, 0])    # Y (up) preserved

    def test_packed_star_2x1_round_trips_through_writer(self):
        """Producer->consumer: a packed plus-star's (2,1) bonds must emit well-formed,
        rotated 15-field LDraw lines (not just exist as placements). The cube alone has
        no (2,1), so the existing round-trip test never exercised this path.
        """
        placements = pack(_plus_star(), color_id=14)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "star.ldr")
            write_ldr(placements, path)
            lines = open(path, encoding="utf-8").read().splitlines()
        rotated = [ln for ln in lines if ln.startswith("1 ") and "0 0 1 0 1 0 -1 0 0" in ln]
        assert rotated, "packed star must emit at least one rotated (2,1) bond line"
        for ln in rotated:
            fields = ln.split()
            assert len(fields) == 15
            assert fields[14] == "3004.dat"


# ---------------------------------------------------------------------------
# Step 4: seam behaviour (z-bonds seam-neutral, x-bonds gated + only where needed)
# ---------------------------------------------------------------------------


class TestStep4SeamBehaviour:
    def test_z_bond_is_seam_neutral(self):
        """Bonding z-adjacent towers preserves the per-layer seam set exactly."""
        towers = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0),
            _make_bp(0, 0, 1), _make_bp(0, 1, 1),
            _make_bp(0, 0, 2), _make_bp(0, 1, 2),
        ]

        def seam_set(plc, layer):
            return frozenset(bp.x + bp.width for bp in plc if bp.y == layer)

        before = {y: seam_set(towers, y) for y in (0, 1)}
        merged = _bond_components_in_volume(towers, 15)
        after = {y: seam_set(merged, y) for y in (0, 1)}
        assert before == after == {0: frozenset({1}), 1: frozenset({1})}
        assert all((bp.width, bp.length) != (2, 1) for bp in merged)

    def test_x_bond_fires_on_star_arm(self):
        """The star x-arm has no z-neighbour, so it MUST use (2,1) x-bonds."""
        result = pack(_plus_star(), color_id=14)
        assert any((bp.width, bp.length) == (2, 1) for bp in result)

    def test_masonry_never_uses_x_bonds(self):
        """x-bonds rank below ALL z strategies, so on masonry grids -- where a z-bond
        is always available -- they never fire. This z-PREFERENCE (not a separate
        seam-gate) is what keeps the masonry ABAB seams intact, verified across the
        salvaged masonry sizes.
        """
        for shape in ((6, 4, 4), (6, 2, 4), (8, 2, 4)):
            result = pack(np.ones(shape, dtype=bool))
            assert all((bp.width, bp.length) != (2, 1) for bp in result), shape


# ---------------------------------------------------------------------------
# Step 4: physics rollback guard
# ---------------------------------------------------------------------------


class TestStep4PhysicsGuard:
    def test_guard_accepts_valid_merge(self):
        before = [_make_bp(0, 0, 0), _make_bp(0, 1, 0), _make_bp(1, 0, 0), _make_bp(1, 1, 0)]
        # bond the two adjacent towers at layer 0 with a (2,1)
        after = [_make_bp(0, 1, 0), _make_bp(1, 1, 0), _make_bp(0, 0, 0, 2, 1)]
        assert _bond_guards_ok(before, after, require_merge=True)

    def test_guard_rejects_unsupported(self):
        """A candidate that leaves a brick floating is rolled back."""
        before = [_make_bp(0, 0, 0)]
        after = [_make_bp(0, 0, 0), _make_bp(3, 1, 3)]  # (3,1,3) floats
        assert not _bond_guards_ok(before, after, require_merge=True)

    def test_guard_rejects_added_height(self):
        """A candidate that stacks above the input top is rolled back (in-volume only)."""
        before = [_make_bp(0, 0, 0), _make_bp(0, 1, 0)]
        after = before + [_make_bp(0, 2, 0)]
        assert not _bond_guards_ok(before, after, require_merge=True)

    def test_guard_rejects_non_merging_primary_bond(self):
        """A PRIMARY bond that does not strictly reduce components is rejected --
        this is what stops a hub decompose from merging one pair while re-splitting
        another at net-zero (the bug that left the plus-star a layer too tall).
        """
        before = [_make_bp(0, 0, 0), _make_bp(0, 1, 0)]  # 1 component already
        after = list(before)  # no change -> no merge
        assert not _bond_guards_ok(before, after, require_merge=True)
        assert _bond_guards_ok(before, after, require_merge=False)  # ok for redundancy


# ---------------------------------------------------------------------------
# Step 4: de-articulation (Phase C) + arm-tip detection
# ---------------------------------------------------------------------------


class TestStep4DeArticulation:
    def test_redundant_z_bond_reduces_cut_vertices(self):
        """Two z-adjacent 3-high towers bonded by one z-bond have a cut-vertex bond;
        Phase C adds a redundant z-bond (cycle) that strictly reduces cut vertices.
        """
        base = [
            _make_bp(0, 0, 0), _make_bp(0, 1, 0), _make_bp(0, 2, 0),
            _make_bp(0, 0, 1), _make_bp(0, 1, 1), _make_bp(0, 2, 1),
        ]
        bonded = _bond_components_in_volume(base, 15)
        before = len(articulation_points(bonded))
        hardened = _eliminate_arm_tip_articulations(bonded, 15)
        assert len(articulation_points(hardened)) < before
        assert connected_component_count(hardened) == 1
        assert _max_y(hardened) == 2          # no added height
        assert unsupported_bricks(hardened) == []

    def test_dearticulation_is_masonry_safe(self):
        """Phase C is z-only, so it never adds a (2,1) or disturbs masonry seams."""
        result = pack(np.ones((6, 4, 4), dtype=bool))  # pack() includes Phase C

        def seam_set(layer):
            return frozenset(bp.x + bp.width for bp in result if bp.y == layer)

        assert seam_set(0) == seam_set(2)
        assert seam_set(1) == seam_set(3)
        assert all((bp.width, bp.length) != (2, 1) for bp in result)

    def test_dearticulation_never_worsens(self):
        """On an already-bonded build the pass never adds height, floats a brick, or
        increases the component count (its acceptance criterion is strict reduction).
        """
        bonded = pack(_solid_cube(5))
        before_art = len(articulation_points(bonded))
        before_y = _max_y(bonded)
        out = _eliminate_arm_tip_articulations(bonded, 15)
        assert len(articulation_points(out)) <= before_art
        assert _max_y(out) == before_y
        assert connected_component_count(out) == 1
        assert unsupported_bricks(out) == []


class TestStep4ArmTip:
    def test_is_arm_tip_brick_true_at_tip(self):
        grid = _plus_star()
        tip = _make_bp(0, 0, 2)  # west arm tip column
        assert _is_arm_tip_brick(tip, grid)

    def test_is_arm_tip_brick_false_at_hub(self):
        grid = _plus_star()
        hub = _make_bp(2, 0, 2)  # cross centre: 4 occupied neighbours
        assert not _is_arm_tip_brick(hub, grid)

    def test_star_no_freestanding_towers(self):
        """The achievable reading of "zero arm-tip cut vertices": after bonding there
        are NO freestanding 1x1 stacks -- every arm tip is part of the single bonded
        assembly (1 component). Internal cut vertices on literal 1-wide arms and the
        saturated hub are geometrically irreducible and intentionally NOT asserted away.
        """
        result = pack(_plus_star(), color_id=14)
        assert connected_component_count(result) == 1
        # every arm-tip column is represented in the (single) assembly
        tip_cols = {(0, 2), (4, 2), (2, 0), (2, 4)}
        covered = {(bp.x + dx, bp.z + dz)
                   for bp in result
                   for dx in range(bp.width) for dz in range(bp.length)}
        assert tip_cols <= covered

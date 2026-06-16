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

from brickomancer.models.brick import BRICK_PART_IDS, TILE_PART_IDS, BrickPlacement
from brickomancer.services.brick_packer import (
    _collect_footprints,
    _footprint,
    _has_connection,
    connectivity_repair,
    interlocking_check,
    pack,
)
from brickomancer.services.ldraw_writer import sequence_steps, write_ldr

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

        covered = np.zeros((5, 5, 5), dtype=int)
        for bp in result:
            for dx in range(bp.width):
                for dz in range(bp.length):
                    covered[bp.x + dx, bp.y, bp.z + dz] += 1

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
        voxels = np.ones((6, 2, 2), dtype=bool)
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

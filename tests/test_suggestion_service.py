"""Tests for suggestion_service.generate_suggestions().

Strategy
--------
- Mock ``run_ldview`` so it creates the output PNG file (touching it is
  sufficient — preview_url only needs the file to exist for the URL to be
  non-empty; the actual PNG content is irrelevant here).
- Use a realistic cylinder-shaped voxel grid so compact < standard pack counts
  diverge naturally.
- All assertions match the done-when criteria from the build plan.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from brickomancer.models.brick import ColorMatch
from brickomancer.models.schemas import Suggestion
from brickomancer.services.suggestion_service import generate_suggestions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cylinder_grid(radius: int = 5, height: int = 4) -> np.ndarray:
    """Return a solid cylinder voxel grid of shape (2r, height, 2r)."""
    size = radius * 2
    grid = np.zeros((size, height, size), dtype=bool)
    cx = cz = radius - 0.5
    for x in range(size):
        for z in range(size):
            if (x - cx) ** 2 + (z - cz) ** 2 <= (radius - 0.5) ** 2:
                grid[x, :, z] = True
    return grid


def _dominant_color() -> list[ColorMatch]:
    """Return a single-entry color list with a known LDraw color (white=15)."""
    return [
        ColorMatch(
            color_id=15,
            color_name="White",
            hex="F4F4F4",
            cluster_weight=1.0,
        )
    ]


def _mock_ldview(ldr_path: str, output_png: str) -> None:
    """Touch the output PNG so the file exists (no actual LDView needed)."""
    Path(output_png).touch()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a fresh temporary directory for each test."""
    return tmp_path


@pytest.fixture()
def request_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def cylinder_grid() -> np.ndarray:
    return _cylinder_grid()


@pytest.fixture()
def colors() -> list[ColorMatch]:
    return _dominant_color()


# ---------------------------------------------------------------------------
# Core contract tests
# ---------------------------------------------------------------------------


class TestGenerateSuggestions:
    def test_returns_exactly_3_suggestions(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_suggestion_is_suggestion_type(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            assert isinstance(s, Suggestion)

    def test_tier_names_in_order(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        assert result[0].tier == "compact"
        assert result[1].tier == "standard"
        assert result[2].tier == "detailed"

    def test_suggestion_ids_follow_format(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        assert result[0].id == f"{request_id}_0"
        assert result[1].id == f"{request_id}_1"
        assert result[2].id == f"{request_id}_2"

    def test_each_has_non_empty_preview_url(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            assert isinstance(s.preview_url, str)
            assert len(s.preview_url) > 0

    def test_preview_url_points_to_existing_png(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for i, s in enumerate(result):
            png_path = tmp_dir / f"suggestion_{i}_preview.png"
            assert png_path.exists(), f"PNG file not found: {png_path}"

    def test_preview_url_format(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for i, s in enumerate(result):
            expected = f"/static/tmp/{request_id}/suggestion_{i}_preview.png"
            assert s.preview_url == expected

    def test_each_has_non_empty_parts_list(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            assert isinstance(s.parts_list, list)
            assert len(s.parts_list) > 0

    def test_each_has_positive_parts_count(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            assert s.parts_count > 0

    def test_three_different_parts_counts(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        """compact < standard ≤ detailed (all three distinct counts)."""
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        compact_count = result[0].parts_count
        standard_count = result[1].parts_count
        detailed_count = result[2].parts_count

        assert compact_count < standard_count, (
            f"compact ({compact_count}) should be < standard ({standard_count})"
        )
        assert standard_count <= detailed_count, (
            f"standard ({standard_count}) should be ≤ detailed ({detailed_count})"
        )
        # All three must differ
        assert len({compact_count, standard_count, detailed_count}) == 3, (
            f"Expected 3 distinct counts, got compact={compact_count}, "
            f"standard={standard_count}, detailed={detailed_count}"
        )

    def test_ldr_files_written_to_tmp_dir(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for i in range(3):
            ldr_path = tmp_dir / f"suggestion_{i}.ldr"
            assert ldr_path.exists(), f"LDR file not found: {ldr_path}"
            assert ldr_path.stat().st_size > 0, f"LDR file is empty: {ldr_path}"

    def test_parts_count_equals_sum_of_parts_list_qty(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            total_qty = sum(pc.qty for pc in s.parts_list)
            assert s.parts_count == total_qty, (
                f"parts_count={s.parts_count} but sum(qty)={total_qty} for tier={s.tier}"
            )

    def test_parts_list_color_hex_starts_with_hash(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        for s in result:
            for pc in s.parts_list:
                assert pc.color_hex.startswith("#"), (
                    f"color_hex '{pc.color_hex}' should start with '#'"
                )

    def test_empty_colors_raises_value_error(
        self,
        cylinder_grid: np.ndarray,
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        with pytest.raises(ValueError, match="colors must be non-empty"):
            generate_suggestions(cylinder_grid, [], tmp_dir, request_id)

    def test_piece_inventory_accepted_without_error(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        """piece_inventory parameter accepted; not yet applied (reserved)."""
        from brickomancer.models.brick import PieceCount

        inventory = [PieceCount(part_id="3005", qty=100, color="White")]
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(
                cylinder_grid, colors, tmp_dir, request_id, piece_inventory=inventory
            )

        assert len(result) == 3

    def test_ldview_called_three_times(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        """run_ldview must be called once per tier."""
        call_count = 0

        def counting_mock(ldr_path: str, output_png: str) -> None:
            nonlocal call_count
            call_count += 1
            Path(output_png).touch()

        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=counting_mock,
        ):
            generate_suggestions(cylinder_grid, colors, tmp_dir, request_id)

        assert call_count == 3

    def test_tmp_dir_created_if_missing(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        request_id: str,
        tmp_path: Path,
    ) -> None:
        """generate_suggestions creates tmp_dir if it doesn't exist yet."""
        new_dir = tmp_path / "nonexistent_subdir"
        assert not new_dir.exists()

        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            generate_suggestions(cylinder_grid, colors, new_dir, request_id)

        assert new_dir.exists()

    def test_str_tmp_dir_accepted(
        self,
        cylinder_grid: np.ndarray,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        """tmp_dir may be a str, not just a Path."""
        with patch(
            "brickomancer.services.suggestion_service.run_ldview",
            side_effect=_mock_ldview,
        ):
            result = generate_suggestions(
                cylinder_grid, colors, str(tmp_dir), request_id
            )

        assert len(result) == 3


# ---------------------------------------------------------------------------
# subprocess_utils: run_ldview PNG existence check
# ---------------------------------------------------------------------------


class TestRunLdview:
    def test_run_ldview_raises_if_png_not_created(self, tmp_dir: Path) -> None:
        """run_ldview raises RuntimeError when LDView exits 0 but doesn't write the PNG."""
        from unittest.mock import MagicMock

        from brickomancer.utils.subprocess_utils import run_ldview

        fake_ldr = str(tmp_dir / "test.ldr")
        fake_png = str(tmp_dir / "test.png")
        Path(fake_ldr).touch()

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stderr = ""

        with patch("brickomancer.utils.subprocess_utils.shutil.which", return_value="ldview"):
            with patch(
                "brickomancer.utils.subprocess_utils.subprocess.run",
                return_value=fake_result,
            ):
                with pytest.raises(RuntimeError, match="did not write"):
                    run_ldview(fake_ldr, fake_png)


# ---------------------------------------------------------------------------
# empty placements: LDView skipped, preview_url is ""
# ---------------------------------------------------------------------------


class TestGenerateSuggestionsEmptyPlacements:
    def test_generate_suggestions_empty_placements_skips_ldview(
        self,
        colors: list[ColorMatch],
        tmp_dir: Path,
        request_id: str,
    ) -> None:
        """When all tiers produce empty placements, run_ldview is never called."""
        # All-False grid: brick_packer.pack() will return [] for every tier
        empty_grid = np.zeros((4, 4, 4), dtype=bool)

        with patch(
            "brickomancer.services.suggestion_service.run_ldview"
        ) as mock_ldview:
            result = generate_suggestions(empty_grid, colors, tmp_dir, request_id)

        mock_ldview.assert_not_called()
        for s in result:
            assert s.preview_url == "", (
                f"Expected empty preview_url for empty placements, got '{s.preview_url}'"
            )

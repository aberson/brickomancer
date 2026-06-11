"""Tests for color_service — KMeans extraction and ΔE2000 color matching."""

from pathlib import Path
from unittest.mock import patch

import pytest

import brickomancer.services.data_service as ds
from brickomancer.models.brick import ColorMatch
from brickomancer.services.color_service import extract_colors, match_color

# ---------------------------------------------------------------------------
# Fixtures / paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
INTEGRATION_FIXTURES = Path(__file__).parent / "integration" / "fixtures"
CAKE_JPG = INTEGRATION_FIXTURES / "cake.jpg"

# Minimal in-memory palette used by most unit tests so we don't hit the
# real data files.
_PALETTE: list[dict] = [
    {"id": 15, "name": "White", "hex": "F4F4F4", "is_trans": False},
    {"id": 1, "name": "Blue", "hex": "0055BF", "is_trans": False},
    {"id": 4, "name": "Bright_Red", "hex": "C91A09", "is_trans": False},
    {"id": 226, "name": "Cool_Yellow", "hex": "FFD700", "is_trans": False},
    {"id": 135, "name": "Sand_Blue", "hex": "5B6E99", "is_trans": False},
]


@pytest.fixture(autouse=True)
def reset_ds():
    """Reset data_service between tests."""
    ds._reset()
    yield
    ds._reset()


@pytest.fixture()
def mock_palette():
    """Patch list_colors() to return the minimal test palette."""
    with patch("brickomancer.services.color_service.list_colors", return_value=_PALETTE):
        yield


# ---------------------------------------------------------------------------
# Unit tests — match_color
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hex_in", ["F4F4F4", "f4f4f4"])
def test_match_color_case_insensitive(mock_palette, hex_in: str) -> None:
    """match_color returns White (id=15) regardless of hex case."""
    result = match_color(hex_in)
    assert isinstance(result, ColorMatch)
    assert result.color_id == 15
    assert result.color_name == "White"


def test_match_color_with_hash_prefix(mock_palette) -> None:
    """match_color('#F4F4F4') strips leading # correctly."""
    result = match_color("#F4F4F4")
    assert result.color_id == 15


def test_match_color_blue(mock_palette) -> None:
    """match_color('0055BF') returns Blue (id=1)."""
    result = match_color("0055BF")
    assert result.color_id == 1


def test_match_color_returns_colorMatch_with_weight_1(mock_palette) -> None:
    """match_color always returns cluster_weight=1.0."""
    result = match_color("F4F4F4")
    assert result.cluster_weight == 1.0


def test_match_color_red(mock_palette) -> None:
    """match_color for a red-ish hex lands on Bright_Red."""
    result = match_color("CC0000")
    assert result.color_id == 4


def test_match_color_invalid_hex_raises() -> None:
    """match_color raises ValueError on a short/invalid hex string."""
    with pytest.raises(ValueError, match="invalid hex color"):
        match_color("FFF")


def test_match_color_empty_hex_raises() -> None:
    """match_color raises ValueError on an empty string."""
    with pytest.raises(ValueError, match="invalid hex color"):
        match_color("")


# ---------------------------------------------------------------------------
# Unit tests — extract_colors
# ---------------------------------------------------------------------------


def test_extract_colors_returns_list_sorted_by_weight(mock_palette, tmp_path) -> None:
    """extract_colors returns a list[ColorMatch] sorted descending by cluster_weight."""
    import numpy as np
    from PIL import Image

    # 60% white, 40% blue image
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    arr[:6, :] = [244, 244, 244]
    arr[6:, :] = [0, 85, 191]
    img = Image.fromarray(arr, mode="RGB")
    p = tmp_path / "test.jpg"
    img.save(p, format="JPEG")

    results = extract_colors(str(p))
    assert isinstance(results, list)
    assert all(isinstance(c, ColorMatch) for c in results)
    # Sorted descending
    weights = [c.cluster_weight for c in results]
    assert weights == sorted(weights, reverse=True)


def test_extract_colors_weights_sum_to_approx_one(mock_palette, tmp_path) -> None:
    """Cluster weights from extract_colors sum to approximately 1.0."""
    import numpy as np
    from PIL import Image

    # 2-region image: 10 rows white, 10 rows blue — ensures multiple non-trivial clusters
    arr = np.zeros((20, 20, 3), dtype=np.uint8)
    arr[:10, :] = [244, 244, 244]  # white region
    arr[10:, :] = [0, 85, 191]    # blue region
    img = Image.fromarray(arr, mode="RGB")
    p = tmp_path / "two_region.png"
    img.save(p)

    results = extract_colors(str(p))
    total = sum(c.cluster_weight for c in results)
    assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}, expected ~1.0"


def test_extract_colors_small_image_graceful(mock_palette, tmp_path) -> None:
    """extract_colors handles an image with fewer pixels than k=8 without error."""
    import numpy as np
    from PIL import Image

    # 2x2 = 4 pixels; k should be clamped to min(8, 4)=4
    arr = np.array(
        [[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [255, 255, 0]]],
        dtype=np.uint8,
    )
    img = Image.fromarray(arr, mode="RGB")
    p = tmp_path / "tiny.png"
    img.save(p)

    results = extract_colors(str(p))
    assert len(results) <= 4


def test_extract_colors_cluster_weight_in_range(mock_palette, tmp_path) -> None:
    """Every cluster_weight returned by extract_colors is in [0.0, 1.0]."""
    import numpy as np
    from PIL import Image

    arr = np.full((10, 10, 3), 200, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    p = tmp_path / "uniform.png"
    img.save(p)

    results = extract_colors(str(p))
    for item in results:
        assert 0.0 <= item.cluster_weight <= 1.0


# ---------------------------------------------------------------------------
# Integration test — cake.jpg produces expected dominant colors
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CAKE_JPG.exists(), reason="cake.jpg fixture not found")
def test_extract_colors_cake_dominant_colors() -> None:
    """extract_colors on cake.jpg returns colors including White, Yellow, and a blue/gray.

    Uses the real LDConfig or CSV palette (real data files if present, else test fixtures).
    Patches list_colors to a richer palette so the test is not data-file dependent.
    """
    rich_palette: list[dict] = [
        {"id": 15, "name": "White", "hex": "F4F4F4", "is_trans": False},
        {"id": 226, "name": "Cool_Yellow", "hex": "FFD700", "is_trans": False},
        {"id": 135, "name": "Sand_Blue", "hex": "5B6E99", "is_trans": False},
        {"id": 138, "name": "Sand_Green", "hex": "A0BCAC", "is_trans": False},
        {"id": 19, "name": "Tan", "hex": "E4CD9E", "is_trans": False},
        {"id": 1, "name": "Blue", "hex": "0055BF", "is_trans": False},
        {"id": 4, "name": "Bright_Red", "hex": "C91A09", "is_trans": False},
        {"id": 0, "name": "Black", "hex": "1B2A34", "is_trans": False},
    ]
    with patch("brickomancer.services.color_service.list_colors", return_value=rich_palette):
        results = extract_colors(str(CAKE_JPG))

    assert len(results) > 0
    color_names = {c.color_name for c in results}
    # The fixture has a white region → must match White
    assert "White" in color_names, f"Expected White in {color_names}"
    # The fixture has a yellow region → must match Cool_Yellow
    assert "Cool_Yellow" in color_names, f"Expected Cool_Yellow in {color_names}"
    # The fixture has a blue-gray region → Sand_Blue or Blue
    blue_gray = {"Sand_Blue", "Blue"}
    assert color_names & blue_gray, f"Expected a blue/gray variant in {color_names}"


def test_match_color_f4f4f4_returns_white_id_15() -> None:
    """match_color('F4F4F4') returns White (id=15) using an inline palette."""
    test_palette: list[dict] = [
        {"id": 15, "name": "White", "hex": "F4F4F4", "is_trans": False},
        {"id": 1, "name": "Blue", "hex": "0055BF", "is_trans": False},
        {"id": 4, "name": "Bright_Red", "hex": "C91A09", "is_trans": False},
    ]
    with patch("brickomancer.services.color_service.list_colors", return_value=test_palette):
        result = match_color("F4F4F4")
    assert result.color_id == 15, (
        f"Expected id=15 (White), got {result.color_id} ({result.color_name})"
    )

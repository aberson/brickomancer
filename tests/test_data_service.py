"""Tests for data_service — colors, parts, lazy init, and /api/colors endpoint."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import brickomancer.services.data_service as ds
from brickomancer.main import app

FIXTURES = Path(__file__).parent / "fixtures"
TEST_LDCONFIG = FIXTURES / "LDConfig_test.ldr"
TEST_COLORS_CSV = FIXTURES / "colors_test.csv"
TEST_PARTS_CSV = FIXTURES / "parts_test.csv"

REAL_COLORS_CSV = Path(__file__).parent.parent / "data" / "rebrickable" / "colors.csv"


@pytest.fixture(autouse=True)
def reset_data_service():
    """Reset data_service state before and after each test."""
    ds._reset()
    yield
    ds._reset()


@pytest.fixture()
def patched_paths():
    """Patch data_service path constants to point at test fixtures."""
    with (
        patch.object(ds, "_LDCONFIG_PATH", TEST_LDCONFIG),
        patch.object(ds, "_COLORS_CSV_PATH", TEST_COLORS_CSV),
        patch.object(ds, "_PARTS_CSV_PATH", TEST_PARTS_CSV),
    ):
        yield


@pytest.fixture()
def client_with_fixtures(patched_paths) -> TestClient:
    """TestClient with data paths patched to test fixtures."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests using fixtures
# ---------------------------------------------------------------------------


def test_get_color_white_returns_correct_hex(patched_paths) -> None:
    """After initialize(), get_color(15) returns hex='F4F4F4' and name containing 'white'."""
    ds.initialize()
    color = ds.get_color(15)
    assert color is not None
    assert color["hex"].upper() == "F4F4F4"
    assert "white" in color["name"].lower()


def test_list_colors_fixture_excludes_transparent(patched_paths) -> None:
    """list_colors() from fixtures excludes the Trans_Clear entry (is_trans=True)."""
    ds.initialize()
    colors = ds.list_colors()
    assert len(colors) >= 1
    for c in colors:
        assert c["is_trans"] is False, f"Transparent color leaked: {c}"


def test_get_color_returns_none_for_unknown(patched_paths) -> None:
    """get_color(99999) returns None."""
    ds.initialize()
    assert ds.get_color(99999) is None


def test_get_part_returns_known_part(patched_paths) -> None:
    """get_part('3001') returns a dict with part_num='3001'."""
    ds.initialize()
    part = ds.get_part("3001")
    assert part is not None
    assert part["part_num"] == "3001"


def test_initialize_parses_only_once(patched_paths) -> None:
    """initialize() called twice only triggers one parse (the _initialized guard works)."""
    with patch(
        "brickomancer.services.data_service._parse_ldconfig", wraps=ds._parse_ldconfig
    ) as mock_parse:
        ds.initialize()
        ds.initialize()
    assert mock_parse.call_count == 1, f"Expected 1 parse call, got {mock_parse.call_count}"


def test_ldconfig_takes_priority_over_colors_csv(patched_paths) -> None:
    """When color_id is in both LDConfig and colors.csv, LDConfig name wins."""
    ds.initialize()
    color = ds.get_color(15)
    assert color is not None
    assert color["name"] == "White_LDConfig", (
        f"Expected LDConfig name 'White_LDConfig', got '{color['name']}'"
    )


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


def test_list_colors_falls_back_to_csv_when_ldconfig_missing(tmp_path) -> None:
    """list_colors() returns CSV colors when LDConfig file is absent."""
    with (
        patch.object(ds, "_LDCONFIG_PATH", tmp_path / "nonexistent.ldr"),
        patch.object(ds, "_COLORS_CSV_PATH", TEST_COLORS_CSV),
        patch.object(ds, "_PARTS_CSV_PATH", TEST_PARTS_CSV),
    ):
        ds.initialize()
        colors = ds.list_colors()
    assert len(colors) >= 1, "Expected CSV fallback to produce at least 1 color"
    for c in colors:
        assert c["is_trans"] is False


def test_get_color_returns_csv_color_when_absent_from_ldconfig(patched_paths) -> None:
    """get_color() returns CSV data for a color not in LDConfig."""
    ds.initialize()
    ldconfig_ids = set(ds._ldconfig_colors.keys())
    csv_ids = set(ds._rebrickable_colors.keys())
    csv_only = csv_ids - ldconfig_ids
    if csv_only:
        color = ds.get_color(next(iter(csv_only)))
        assert color is not None
        assert color["hex"]
    else:
        pytest.skip(
            "Test fixtures have identical id sets — add a CSV-only color to colors_test.csv"
        )


def test_lazy_init_triggered_by_get_color_without_explicit_initialize(patched_paths) -> None:
    """get_color() triggers lazy initialization without an explicit initialize() call."""
    assert not ds._initialized
    color = ds.get_color(15)
    assert ds._initialized
    assert color is not None


# ---------------------------------------------------------------------------
# Test using real data files when available
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL_COLORS_CSV.exists(),
    reason="Real data files not present — run scripts/download_data.py first",
)
def test_list_colors_returns_at_least_100() -> None:
    """list_colors() returns ≥100 entries each with non-empty hex (real data files)."""
    # Do NOT use patched_paths — use real data files
    ds.initialize()
    colors = ds.list_colors()
    assert len(colors) >= 100, f"Expected ≥100 colors, got {len(colors)}"
    for c in colors:
        assert c["hex"], f"Empty hex for color {c}"


# ---------------------------------------------------------------------------
# Integration test: /api/colors endpoint through the production route
# ---------------------------------------------------------------------------


def test_api_colors_endpoint_returns_list(client_with_fixtures) -> None:
    """GET /api/colors returns 200 with a list of at least 1 color (fixture data)."""
    response = client_with_fixtures.get("/api/colors")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1, "Expected at least 1 color from fixture data"
    # Spot-check shape
    first = body[0]
    assert "id" in first
    assert "name" in first
    assert "hex" in first
    assert "is_trans" in first

"""Real-path smoke for the scorer's structural half (closes the mock-theater gap).

The regression-gate tests inject a FAKE ``render_and_score``, so ``scorer.py``'s real
structural block (packer connectivity + part variety) was never exercised -- which is
exactly how a crash hid there: ``connected_component_count`` was handed a connectivity
graph instead of the placements list, raising ``AttributeError`` on every real eval item
and blocking the Step 10 calibration. These tests run that real block through the real
packer, no mocks, so the crash class stays caught.
"""

from __future__ import annotations

import numpy as np

from brickomancer.services import brick_packer
from tests.harness import scorer


def _solid_cube(size: int = 5) -> np.ndarray:
    """A fully-occupied cube grid (mirrors tests/test_brick_packer.py's fixture)."""
    return np.ones((size, size, size), dtype=bool)


def test_score_structure_runs_on_real_packer_output() -> None:
    # Regression guard: before the fix this raised AttributeError because
    # connected_component_count was called with a graph, not the placements list.
    placements = brick_packer.pack(_solid_cube(5), color_id=15)
    scores = scorer._score_structure(placements)

    assert set(scores) == {"build_stability", "part_variety"}
    # A solid cube packs into a single fully-supported assembly (1 component, 0
    # unsupported) -> perfect stability. Same anchor as test_brick_packer.py.
    assert scores["build_stability"] == 10.0
    assert 0.0 < scores["part_variety"] <= 10.0


def test_score_structure_empty_grid_is_not_perfect() -> None:
    # A garbage anchor: no placements -> 0 components != 1 -> not perfect stability,
    # and no distinct parts -> 0 variety. Proves the scorer discriminates good from empty.
    scores = scorer._score_structure([])

    assert scores["build_stability"] == 3.0
    assert scores["part_variety"] == 0.0

"""Shape-fidelity integration test using the gold star dataset.

Run with: BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/test_star_pipeline.py -v
"""
import os
from pathlib import Path

import pytest

from brickomancer.services import brick_packer, image_pipeline
from brickomancer.services.suggestion_service import _downsample

STAR_IMAGE = (
    Path(__file__).parent.parent.parent
    / "docs"
    / "example_input_output"
    / "star"
    / "input_image"
    / "cartoon_star2.png"
)

pytestmark = pytest.mark.skipif(
    not os.getenv("BRICKOMANCER_INTEGRATION"),
    reason="set BRICKOMANCER_INTEGRATION=1 to run",
)


def test_star_compact_produces_star_shape() -> None:
    """Full pipeline on cartoon_star2.png must produce a non-degenerate compact build."""
    assert STAR_IMAGE.exists(), f"Gold star image missing: {STAR_IMAGE}"

    voxels = image_pipeline.run(str(STAR_IMAGE), height_studs=5)
    compact = _downsample(voxels)
    placements = brick_packer.pack(compact, color_id=14)

    assert voxels.sum() >= 50, f"Expected >= 50 filled voxels, got {voxels.sum()}"
    assert len(placements) >= 10, f"Expected >= 10 placements, got {len(placements)}"
    assert len(set((b.x, b.z) for b in placements)) >= 5, (
        f"Expected >= 5 distinct XZ positions, "
        f"got {len(set((b.x, b.z) for b in placements))}"
    )

"""Re-render + re-score the eval set (Step 9 scorer).

The rung the v1 gate was missing: after a change passes pytest, the loop must
re-render the eval set and re-score it, committing only if no dimension regresses.

``render_and_score`` here is the REAL path (renders each eval build and scores it from
the rendered artifacts). It is SLOW (real pipeline + LDView/LPub3D, plus ~17 min/item
for the image path) and is exercised end-to-end in Step 10 (calibration). Step 9's
regression-gate test does NOT call it — it injects a deterministic fake — so the gate
logic is tested fast while this stays the production scorer.

Scoring is deterministic-structural (page count, PDF validity, packer connectivity,
part variety) rather than an LLM judge: a regression gate wants a stable, reproducible
signal, and the headline regression to catch — a blanked PDF — is detected exactly by
``pdf_completeness`` (page count) dropping to 0. Richer LLM-judged dimensions can layer
on top in Step 10 without changing the gate (which is score-source-agnostic).
"""

from __future__ import annotations

# The fixed eval set (text descriptions — fast enough to re-score each iteration; the
# image path is correct but ~17 min/item, so it is opt-in for a calibration run).
EVAL_SET: tuple[tuple[str, str], ...] = (
    ("star", "a five-pointed star"),
    ("dog", "a dog"),
    ("chair", "a chair"),
    ("heart", "a heart"),
)

# Dimensions the structural scorer reports (0.0–10.0 each, matching the v1 raw scale).
SCORE_DIMENSIONS: tuple[str, ...] = (
    "pdf_completeness",
    "technical_validity",
    "build_stability",
    "part_variety",
)


def _score_pdf(pdf_path: str) -> dict[str, float]:
    """Deterministic structural scores from a rendered instruction PDF."""
    import re
    from pathlib import Path

    raw = Path(pdf_path).read_bytes()
    page_count = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    return {
        # A blanked/crashed PDF has 0 pages -> 0; multi-page -> scaled, capped at 10.
        "pdf_completeness": min(10.0, float(page_count) * 2.0),
        "technical_validity": 10.0 if len(raw) > 1000 else 0.0,
    }


def render_and_score(project_root: str) -> dict[str, float]:
    """Render the eval set and return averaged per-dimension scores (the slow real path).

    Lazy-imports the pipeline so importing this module stays cheap (no torch/model load
    at collection time). Returns a dict[dimension -> mean score across the eval set].
    """
    import uuid

    from brickomancer.services import (
        brick_packer,
        color_service,
        instruction_service,
        suggestion_service,
        text_shaper,
    )
    from brickomancer.utils.temp_dir import TMP_DIR

    totals: dict[str, list[float]] = {d: [] for d in SCORE_DIMENSIONS}
    colors = [color_service.match_color("#C91A09")]

    for _name, description in EVAL_SET:
        grid = text_shaper.TextShaper(description).to_voxels()

        # build_stability + part_variety from the packed standard-tier grid
        placements = brick_packer.pack(grid, color_id=colors[0].color_id)
        graph = brick_packer.build_connectivity_graph(placements)
        components = brick_packer.connected_component_count(graph)
        unsupported = len(brick_packer.unsupported_bricks(placements))
        distinct_parts = len({bp.part_id for bp in placements})
        totals["build_stability"].append(10.0 if components == 1 and unsupported == 0 else 3.0)
        totals["part_variety"].append(min(10.0, float(distinct_parts) * 2.0))

        # pdf_completeness + technical_validity from a real render
        request_id = str(uuid.uuid4())
        tmp_path = TMP_DIR / request_id
        suggestion_service.generate_suggestions(grid, colors, tmp_path, request_id)
        ldr = tmp_path / "suggestion_1.ldr"  # standard tier
        pdf = instruction_service.generate_pdf(str(ldr), str(tmp_path))
        for dim, val in _score_pdf(pdf).items():
            totals[dim].append(val)

    return {dim: (sum(vals) / len(vals) if vals else 0.0) for dim, vals in totals.items()}

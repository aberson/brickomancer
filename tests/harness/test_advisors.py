"""Validate tests/harness/advisors.yaml schema — no LLM calls.

Checks:
- All 8 advisors are present (by id)
- Each advisor has: id (str), name (str), reads (list, non-empty), prompt (str, non-empty),
  anchors (list of 3 dicts each with score and description)
- The 3 anchors have scores exactly 2, 5, and 8
- The prompt contains the JSON output spec fields: "score", "confidence", "findings"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Load the YAML once for all tests
# ---------------------------------------------------------------------------

ADVISORS_YAML = Path(__file__).parent / "advisors.yaml"

EXPECTED_IDS = {
    "shape_fidelity",
    "color_match",
    "build_stability",
    "instruction_clarity",
    "aesthetics",
    "pdf_completeness",
    "technical_validity",
    "reference_fidelity",
}

EXPECTED_ANCHOR_SCORES = {2, 5, 8}


@pytest.fixture(scope="module")
def advisors_doc() -> dict[str, Any]:
    """Load and return the parsed advisors YAML document."""
    assert ADVISORS_YAML.exists(), f"advisors.yaml not found at {ADVISORS_YAML}"
    with ADVISORS_YAML.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return doc  # type: ignore[return-value]


@pytest.fixture(scope="module")
def advisors_by_id(advisors_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a dict mapping advisor id -> advisor dict."""
    advisors: list[dict[str, Any]] = advisors_doc["advisors"]
    return {a["id"]: a for a in advisors}


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------


def test_yaml_version(advisors_doc: dict[str, Any]) -> None:
    """YAML document has a 'version' key."""
    assert "version" in advisors_doc, "YAML missing 'version' key"
    assert isinstance(advisors_doc["version"], str), "'version' must be a string"


def test_yaml_has_advisors_list(advisors_doc: dict[str, Any]) -> None:
    """YAML document has an 'advisors' list."""
    assert "advisors" in advisors_doc, "YAML missing 'advisors' key"
    assert isinstance(advisors_doc["advisors"], list), "'advisors' must be a list"


def test_all_eight_advisors_present(advisors_by_id: dict[str, dict[str, Any]]) -> None:
    """All 8 required advisor IDs are present."""
    missing = EXPECTED_IDS - set(advisors_by_id.keys())
    assert not missing, f"Missing advisor IDs: {missing}"


def test_no_duplicate_advisor_ids(advisors_doc: dict[str, Any]) -> None:
    """No two advisors share the same id."""
    ids = [a["id"] for a in advisors_doc["advisors"]]
    assert len(ids) == len(set(ids)), f"Duplicate advisor IDs found: {ids}"


def test_advisor_count_is_exactly_nine(advisors_doc: dict[str, Any]) -> None:
    """Exactly 9 advisors are defined (8 quality + warnings_judge)."""
    assert len(advisors_doc["advisors"]) == 9, (
        f"Expected 9 advisors, found {len(advisors_doc['advisors'])}"
    )


# ---------------------------------------------------------------------------
# Per-advisor field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_id_is_string(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor's 'id' field is a non-empty string."""
    advisor = advisors_by_id[advisor_id]
    assert isinstance(advisor["id"], str), f"{advisor_id}: 'id' must be a string"
    assert advisor["id"].strip(), f"{advisor_id}: 'id' must not be empty"


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_name_is_string(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor has a non-empty 'name' string."""
    advisor = advisors_by_id[advisor_id]
    assert "name" in advisor, f"{advisor_id}: missing 'name' field"
    assert isinstance(advisor["name"], str), f"{advisor_id}: 'name' must be a string"
    assert advisor["name"].strip(), f"{advisor_id}: 'name' must not be empty"


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_reads_is_nonempty_list(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor has a non-empty 'reads' list."""
    advisor = advisors_by_id[advisor_id]
    assert "reads" in advisor, f"{advisor_id}: missing 'reads' field"
    assert isinstance(advisor["reads"], list), f"{advisor_id}: 'reads' must be a list"
    assert len(advisor["reads"]) > 0, f"{advisor_id}: 'reads' must not be empty"
    for item in advisor["reads"]:
        assert isinstance(item, str), f"{advisor_id}: each 'reads' entry must be a string"


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_prompt_is_nonempty_string(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor has a non-empty 'prompt' string."""
    advisor = advisors_by_id[advisor_id]
    assert "prompt" in advisor, f"{advisor_id}: missing 'prompt' field"
    assert isinstance(advisor["prompt"], str), f"{advisor_id}: 'prompt' must be a string"
    assert advisor["prompt"].strip(), f"{advisor_id}: 'prompt' must not be empty"


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_prompt_contains_json_output_spec(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor's prompt contains the JSON output spec fields: score, confidence, findings."""
    advisor = advisors_by_id[advisor_id]
    prompt = advisor["prompt"]
    for field in ("score", "confidence", "findings"):
        assert field in prompt, (
            f"{advisor_id}: prompt must contain '{field}' as part of the JSON output spec"
        )


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_anchors_is_list_of_three(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor has exactly 3 anchors."""
    advisor = advisors_by_id[advisor_id]
    assert "anchors" in advisor, f"{advisor_id}: missing 'anchors' field"
    assert isinstance(advisor["anchors"], list), f"{advisor_id}: 'anchors' must be a list"
    assert len(advisor["anchors"]) == 3, (
        f"{advisor_id}: expected 3 anchors, found {len(advisor['anchors'])}"
    )


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_anchor_scores_are_2_5_8(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each advisor's anchors have scores exactly 2, 5, and 8."""
    advisor = advisors_by_id[advisor_id]
    scores = {anchor["score"] for anchor in advisor["anchors"]}
    assert scores == EXPECTED_ANCHOR_SCORES, (
        f"{advisor_id}: expected anchor scores {{2, 5, 8}}, found {scores}"
    )


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_IDS))
def test_advisor_anchor_descriptions_nonempty(
    advisor_id: str, advisors_by_id: dict[str, dict[str, Any]]
) -> None:
    """Each anchor has a non-empty 'description' string."""
    advisor = advisors_by_id[advisor_id]
    for i, anchor in enumerate(advisor["anchors"]):
        assert "description" in anchor, (
            f"{advisor_id}: anchor[{i}] missing 'description' field"
        )
        assert isinstance(anchor["description"], str), (
            f"{advisor_id}: anchor[{i}]['description'] must be a string"
        )
        assert anchor["description"].strip(), (
            f"{advisor_id}: anchor[{i}]['description'] must not be empty"
        )


# ---------------------------------------------------------------------------
# Known reads contract per advisor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "advisor_id, expected_reads",
    [
        ("shape_fidelity", ["preview_png", "input_image"]),
        ("color_match", ["preview_png", "input_image"]),
        ("build_stability", ["ldr_file"]),
        ("instruction_clarity", ["pdf", "preview_png"]),
        ("aesthetics", ["preview_png", "pdf_first_page", "input_image"]),
        ("pdf_completeness", ["pdf"]),
        ("technical_validity", ["ldr_file", "parts_list"]),
    ],
)
def test_advisor_reads_matches_spec(
    advisor_id: str,
    expected_reads: list[str],
    advisors_by_id: dict[str, dict[str, Any]],
) -> None:
    """Each advisor's 'reads' list matches the specification exactly."""
    advisor = advisors_by_id[advisor_id]
    assert advisor["reads"] == expected_reads, (
        f"{advisor_id}: expected reads {expected_reads}, found {advisor['reads']}"
    )

"""Piece detector — identifies LEGO pieces from photos via Claude subprocess.

Implemented in Step 7.
"""

import json
import re
import subprocess

from brickomancer.models.brick import PieceCount
from brickomancer.utils.subprocess_utils import run_claude_subprocess

# Prompt from plan Appendix §12.4
_DETECTION_PROMPT = (
    "You are a LEGO piece identifier. Identify all visible LEGO pieces in this image.\n"
    "Return ONLY valid JSON as a list — no other text:\n"
    '[{"part_id": "<4-or-5-digit-lego-part-number>", "qty": <integer>,'
    ' "color": "<lego_color_name>"}, ...]\n'
    "If you cannot identify a piece with confidence, omit it entirely.\n"
    "Common part IDs: 3001 (2×4 brick), 3003 (2×2 brick), 3004 (1×2 brick), 3005 (1×1 brick),\n"
    "3010 (1×4 brick), 60474 (4×4 round plate), 11213 (6×6 round plate)."
)

# V1: accept only 4-5 digit numeric part IDs (covers standard bricks).
# Alphanumeric IDs (e.g. 973pb0) are filtered out — known limitation.
_PART_ID_RE = re.compile(r"^\d{4,5}$")


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences from Claude output."""
    text = text.strip()
    # Remove opening fence (```json or ```)
    text = re.sub(r"^```(?:json)?\s*", "", text)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_pieces(raw_output: str) -> list[PieceCount]:
    """Parse raw Claude output into a list of PieceCount.

    Strips markdown fences, parses JSON, validates part_ids.

    Raises:
        json.JSONDecodeError: If the output is not valid JSON.
        ValueError: If the JSON root is not a list.
    """
    cleaned = _strip_markdown_fences(raw_output)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list, got {type(data).__name__}")
    pieces: list[PieceCount] = []
    for item in data:
        part_id = str(item.get("part_id", "")).strip()
        if not _PART_ID_RE.match(part_id):
            continue  # filter invalid part_ids
        qty = int(item.get("qty", 0))
        color = str(item.get("color", "")).strip()
        if qty > 0 and color:
            pieces.append(PieceCount(part_id=part_id, qty=qty, color=color))
    return pieces


def _detect_from_image(image_path: str) -> list[PieceCount]:
    """Detect pieces from a single image with up to 2 retries on parse failure."""
    max_attempts = 3  # 1 initial + 2 retries
    for attempt in range(max_attempts):
        try:
            raw = run_claude_subprocess(_DETECTION_PROMPT, image_path)
            return _parse_pieces(raw)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            if attempt == max_attempts - 1:
                # All retries exhausted — graceful degradation
                return []
            # retry
        except (RuntimeError, subprocess.TimeoutExpired):
            # Subprocess failure or timeout — no point retrying
            return []
    return []  # unreachable but satisfies type checker


def detect_pieces(image_paths: list[str]) -> list[PieceCount]:
    """Detect LEGO pieces in one or more photos using the Claude subprocess.

    Args:
        image_paths: List of paths to piece photo files.

    Returns:
        list[PieceCount] with detected pieces and quantities, merged across all images.
    """
    all_lists: list[list[PieceCount]] = []
    for path in image_paths:
        pieces = _detect_from_image(path)
        all_lists.append(pieces)
    return merge_piece_lists(all_lists)


def merge_piece_lists(lists: list[list[PieceCount]]) -> list[PieceCount]:
    """Merge multiple PieceCount lists, summing quantities for duplicate (part_id, color) pairs.

    Args:
        lists: List of list[PieceCount] from multiple photos.

    Returns:
        Merged list[PieceCount], sorted by part_id.
    """
    totals: dict[tuple[str, str], int] = {}
    for piece_list in lists:
        for pc in piece_list:
            key = (pc.part_id, pc.color)
            totals[key] = totals.get(key, 0) + pc.qty

    merged = [
        PieceCount(part_id=part_id, qty=qty, color=color)
        for (part_id, color), qty in totals.items()
    ]
    merged.sort(key=lambda pc: pc.part_id)
    return merged

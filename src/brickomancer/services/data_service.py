"""Data service — loads Rebrickable CSVs and LDConfig.ldr.

Lazy-loading: files are parsed on first call, not at import time.
Call ``initialize()`` at startup to warm the cache before the first request.
"""

import csv
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# File paths (module-level constants so tests can monkeypatch them)
# ---------------------------------------------------------------------------
# src/brickomancer/services/ -> src/brickomancer/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_LDCONFIG_PATH: Path = _REPO_ROOT / "data" / "ldraw" / "LDConfig.ldr"
_COLORS_CSV_PATH: Path = _REPO_ROOT / "data" / "rebrickable" / "colors.csv"
_PARTS_CSV_PATH: Path = _REPO_ROOT / "data" / "rebrickable" / "parts.csv"

# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------
_init_lock = threading.Lock()
_initialized: bool = False
# {color_id: {id, name, hex, is_trans}}
_ldconfig_colors: dict[int, dict] = {}
# {color_id: {id, name, hex, is_trans}}
_rebrickable_colors: dict[int, dict] = {}
# {part_num: {part_num, name, part_cat_id}}
_parts: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_ldconfig(path: Path) -> dict[int, dict]:
    """Parse ``!COLOUR`` entries from an LDConfig.ldr file.

    Line format::

        0 !COLOUR White   CODE 15  VALUE #F4F4F4  EDGE #9C9291  [ALPHA nnn]

    Returns a mapping from integer code → color dict.
    """
    colors: dict[int, dict] = {}
    if not path.exists():
        return colors
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if "!COLOUR" not in line:
                continue
            tokens = line.split()
            try:
                colour_idx = tokens.index("!COLOUR")
            except ValueError:
                continue
            # Name is the token immediately after !COLOUR
            if colour_idx + 1 >= len(tokens):
                continue
            name = tokens[colour_idx + 1]
            # Find CODE and VALUE
            try:
                code_idx = tokens.index("CODE")
                code = int(tokens[code_idx + 1])
            except (ValueError, IndexError):
                continue
            try:
                value_idx = tokens.index("VALUE")
                hex_val = tokens[value_idx + 1].removeprefix("#")
            except (ValueError, IndexError):
                continue
            # ALPHA token present → transparent
            is_trans = "ALPHA" in tokens
            colors[code] = {
                "id": code,
                "name": name,
                "hex": hex_val,
                "is_trans": is_trans,
            }
    return colors


def _parse_colors_csv(path: Path) -> dict[int, dict]:
    """Parse a Rebrickable colors.csv file.

    Expected columns (at minimum): id, name, rgb, is_trans
    """
    colors: dict[int, dict] = {}
    if not path.exists():
        return colors
    with path.open(encoding="utf-8", newline="", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                color_id = int(row["id"])
            except (KeyError, ValueError):
                continue
            is_trans_raw = row.get("is_trans", "False").strip().lower()
            is_trans = is_trans_raw in ("true", "1", "t", "yes")
            colors[color_id] = {
                "id": color_id,
                "name": row.get("name", ""),
                "hex": row.get("rgb", "").strip().removeprefix("#"),
                "is_trans": is_trans,
            }
    return colors


def _parse_parts_csv(path: Path) -> dict[str, dict]:
    """Parse a Rebrickable parts.csv file.

    Expected columns: part_num, name, part_cat_id
    """
    parts: dict[str, dict] = {}
    if not path.exists():
        return parts
    with path.open(encoding="utf-8", newline="", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            part_num = row.get("part_num", "").strip()
            if not part_num:
                continue
            parts[part_num] = {
                "part_num": part_num,
                "name": row.get("name", ""),
                "part_cat_id": row.get("part_cat_id", ""),
            }
    return parts


# ---------------------------------------------------------------------------
# Lazy init
# ---------------------------------------------------------------------------

def _ensure_initialized() -> None:
    global _initialized, _ldconfig_colors, _rebrickable_colors, _parts
    if _initialized:
        return
    with _init_lock:
        if _initialized:  # double-checked locking
            return
        _ldconfig_colors = _parse_ldconfig(_LDCONFIG_PATH)
        _rebrickable_colors = _parse_colors_csv(_COLORS_CSV_PATH)
        _parts = _parse_parts_csv(_PARTS_CSV_PATH)
        _initialized = True


def initialize() -> None:
    """Force lazy-load of all data files. Safe to call multiple times."""
    _ensure_initialized()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_color(color_id: int) -> dict | None:
    """Return ``{id, name, hex, is_trans}`` for *color_id*, or ``None`` if not found.

    LDConfig.ldr takes priority over colors.csv.
    """
    _ensure_initialized()
    entry = _ldconfig_colors.get(color_id)
    if entry is not None:
        return entry
    return _rebrickable_colors.get(color_id)


def get_part(part_num: str) -> dict | None:
    """Return ``{part_num, name, part_cat_id}`` for *part_num*, or ``None`` if not found."""
    _ensure_initialized()
    return _parts.get(part_num)


def list_colors() -> list[dict]:
    """Return all solid (non-transparent) colors from LDConfig.ldr.

    Each entry: ``{id: int, name: str, hex: str, is_trans: bool}``.
    Falls back to colors.csv if LDConfig produced no results.
    """
    _ensure_initialized()
    source = _ldconfig_colors if _ldconfig_colors else _rebrickable_colors
    return [c for c in source.values() if not c["is_trans"]]


def _reset() -> None:
    """Reset module state. For use in tests only."""
    global _initialized, _ldconfig_colors, _rebrickable_colors, _parts
    with _init_lock:
        _initialized = False
        _ldconfig_colors = {}
        _rebrickable_colors = {}
        _parts = {}

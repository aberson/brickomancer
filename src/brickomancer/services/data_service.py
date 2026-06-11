"""Data service — loads Rebrickable CSVs and LDConfig.ldr at startup.

Implemented in Step 2.
"""


def get_color(color_id: int) -> dict:  # type: ignore[empty-body]
    """Return color data for a given Rebrickable color ID."""
    ...


def get_part(part_num: str) -> dict:  # type: ignore[empty-body]
    """Return part data for a given Rebrickable part number."""
    ...


def list_colors() -> list:  # type: ignore[empty-body]
    """Return all available LEGO colors."""
    ...

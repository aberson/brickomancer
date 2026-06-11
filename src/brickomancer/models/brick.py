"""Brick dataclasses and constants for Brickomancer.

CRITICAL: BRICK_TYPES is the single source of truth for supported brick sizes.
All other modules (ldraw_writer, suggestion_service, brick_packer) must import
from here — never redefine.
"""

from dataclasses import dataclass, field

# Single source of truth for supported brick dimensions (width, length) in studs.
# Sorted largest-first so the packer tries big bricks before small ones.
BRICK_TYPES: list[tuple[int, int]] = [(2, 4), (2, 3), (2, 2), (1, 4), (1, 3), (1, 2), (1, 1)]

# Mapping from (width, length) to LDraw part ID
BRICK_PART_IDS: dict[tuple[int, int], str] = {
    (2, 4): "3001",
    (2, 3): "3002",
    (2, 2): "3003",
    (1, 4): "3010",
    (1, 3): "3622",
    (1, 2): "3004",
    (1, 1): "3005",
}


@dataclass
class BrickPlacement:
    """Represents a single placed brick in the build."""

    part_id: str
    color_id: int
    x: int
    y: int
    z: int
    width: int
    length: int


@dataclass
class ColorMatch:
    """A matched LEGO color for a given input color."""

    color_id: int
    color_name: str
    hex: str
    cluster_weight: float


@dataclass
class ShapeParams:
    """Structured shape parameters extracted from a text description."""

    archetype: str
    height_studs: int
    radius_studs: int = 0
    width_studs: int = 0
    depth_studs: int = 0
    colors: list[str] = field(default_factory=list)


@dataclass
class PieceCount:
    """A count of available LEGO pieces of a specific type and color."""

    part_id: str
    qty: int
    color: str

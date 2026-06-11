"""Suggestion service — generates 3 LEGO build suggestions from a voxel grid.

Implemented in Step 8.
"""


def generate_suggestions(  # type: ignore[empty-body]
    grid: object,
    colors: list,
    piece_inventory: list | None = None,
) -> list:
    """Generate compact, standard, and detailed LEGO build suggestions.

    Args:
        grid: numpy.ndarray[bool] of shape (X, Y, Z).
        colors: list[ColorMatch] from color_service.
        piece_inventory: Optional list[PieceCount] of available pieces (soft constraint).

    Returns:
        list[Suggestion] with exactly 3 items (compact, standard, detailed).
    """
    ...

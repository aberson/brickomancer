"""Piece detector — identifies LEGO pieces from photos via Claude subprocess.

Implemented in Step 7.
"""


def detect_pieces(image_paths: list) -> list:  # type: ignore[empty-body]
    """Detect LEGO pieces in one or more photos using the Claude subprocess.

    Args:
        image_paths: List of paths to piece photo files.

    Returns:
        list[PieceCount] with detected pieces and quantities.
    """
    ...


def merge_piece_lists(lists: list) -> list:  # type: ignore[empty-body]
    """Merge multiple PieceCount lists, summing quantities for duplicate (part_id, color) pairs.

    Args:
        lists: List of list[PieceCount] from multiple photos.

    Returns:
        Merged list[PieceCount].
    """
    ...

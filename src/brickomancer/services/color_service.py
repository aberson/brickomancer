"""Color service — KMeans color extraction and ΔE2000 LEGO color matching.

Implemented in Step 3.
"""


def extract_colors(image_path: str) -> list:  # type: ignore[empty-body]
    """Extract dominant colors from an image using KMeans in Lab color space.

    Args:
        image_path: Path to the input image.

    Returns:
        list[ColorMatch] sorted by cluster weight (largest cluster first).
    """
    ...


def match_color(rgb_hex: str) -> object:  # type: ignore[empty-body]
    """Find the nearest LEGO color for a given RGB hex string using ΔE2000.

    Args:
        rgb_hex: 6-character hex string (without #), e.g. "F4F4F4".

    Returns:
        ColorMatch with the nearest LEGO color.
    """
    ...

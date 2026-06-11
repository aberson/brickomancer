"""Script to regenerate test fixtures — not a test file."""

from pathlib import Path

import numpy as np
from PIL import Image

FIXTURES = Path(__file__).parent


def make_cake_jpg() -> None:
    """Create a 100x100 JPEG with white, yellow, and blue-gray regions."""
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    # Top-left 50x50: white
    arr[:50, :50] = [244, 244, 244]
    # Top-right 50x50: yellow
    arr[:50, 50:] = [255, 215, 0]
    # Bottom-left 50x50: blue-gray
    arr[50:, :50] = [91, 110, 153]
    # Bottom-right 50x50: light tan/beige
    arr[50:, 50:] = [200, 170, 120]
    img = Image.fromarray(arr, mode="RGB")
    img.save(FIXTURES / "cake.jpg", format="JPEG", quality=95)


if __name__ == "__main__":
    make_cake_jpg()
    print("Created cake.jpg")

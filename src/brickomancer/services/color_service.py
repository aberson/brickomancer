"""Color service â€” KMeans color extraction and Î”E2000 LEGO color matching.

Two public functions:
  extract_colors(image_path) -> list[ColorMatch]
      Runs KMeans (k=8) in Lab color space on the image pixels, then maps
      each cluster centroid to the nearest LEGO color via Î”E2000.

  match_color(rgb_hex) -> ColorMatch
      Maps a single hex string to the nearest LEGO color via Î”E2000.

Dependencies
------------
- basic-colormath  â†’  `basic_colormath` (get_delta_e_lab)
- scikit-image     â†’  `skimage.color.rgb2lab`  (KMeans Lab conversion + palette conversion)
- Pillow           â†’  image loading
- scikit-learn     â†’  KMeans
- numpy
"""

import numpy as np
from basic_colormath.distance import get_delta_e_lab
from PIL import Image
from skimage.color import rgb2lab
from sklearn.cluster import KMeans

from brickomancer.models.brick import ColorMatch
from brickomancer.services.data_service import list_colors

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_K_CLUSTERS = 8  # Number of KMeans clusters

_LAB = tuple[float, float, float]

# Cached palette: list of (color_id, color_name, hex_str, lab) built once on first use.
_palette_lab_cache: list[tuple[int, str, str, _LAB]] | None = None


def _get_palette_lab() -> list[tuple[int, str, str, _LAB]]:
    global _palette_lab_cache
    if _palette_lab_cache is None:
        _palette_lab_cache = []
        for entry in list_colors():
            lego_rgb = _hex_to_rgb255(entry["hex"])
            lego_lab = _rgb255_to_lab(*lego_rgb)
            _palette_lab_cache.append((entry["id"], entry["name"], entry["hex"], lego_lab))
    return _palette_lab_cache


def _hex_to_rgb255(hex_str: str) -> tuple[float, float, float]:
    """Convert a 6-character hex string to an RGB tuple in [0, 255] range."""
    h = hex_str.lstrip("#")
    if len(h) != 6:
        raise ValueError(
            f"invalid hex color '{hex_str}': expected 6-char hex string"
        )
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return float(r), float(g), float(b)


def _rgb255_to_lab(r: float, g: float, b: float) -> _LAB:
    """Convert [0,255] float RGB to CIE Lab using skimage."""
    arr = np.array([[[r / 255.0, g / 255.0, b / 255.0]]], dtype=np.float32)
    lab = rgb2lab(arr)  # shape (1, 1, 3)
    L, a, b_ = float(lab[0, 0, 0]), float(lab[0, 0, 1]), float(lab[0, 0, 2])
    return L, a, b_


def _nearest_lego_color(lab: _LAB) -> tuple[int, str, str]:
    """Find the nearest LEGO color by Î”E2000.

    Args:
        lab: Lab color tuple (L, a, b) as produced by skimage.color.rgb2lab.

    Returns:
        (color_id, color_name, hex_string)
    """
    palette = _get_palette_lab()
    if not palette:
        raise ValueError("list_colors() returned an empty palette")
    best_id, best_name, best_hex = palette[0][0], palette[0][1], palette[0][2]
    best_dist = float("inf")
    for color_id, color_name, hex_str, lego_lab in palette:
        dist = get_delta_e_lab(lab, lego_lab)
        if dist < best_dist:
            best_dist = dist
            best_id, best_name, best_hex = color_id, color_name, hex_str
    return best_id, best_name, best_hex


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_colors(image_path: str) -> list[ColorMatch]:
    """Extract dominant colors from an image using KMeans in Lab color space.

    Args:
        image_path: Path to the input image.

    Returns:
        list[ColorMatch] sorted by cluster weight (largest cluster first).
    """
    with Image.open(image_path) as raw_img:
        img_rgba = raw_img.convert("RGBA")

    arr = np.array(img_rgba, dtype=np.float32)
    alpha = arr[:, :, 3]
    subject_mask = alpha > 10  # exclude background pixels removed by rembg

    if subject_mask.any():
        flat_rgb = arr[subject_mask, :3] / 255.0  # (N, 3) in [0, 1]
    else:
        flat_rgb = (arr[:, :, :3] / 255.0).reshape(-1, 3)

    n_pixels = flat_rgb.shape[0]

    # Convert to Lab space for perceptually uniform clustering
    flat_lab = rgb2lab(flat_rgb.reshape(1, n_pixels, 3)).reshape(n_pixels, 3)  # (N, 3)

    k = min(_K_CLUSTERS, n_pixels)
    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = kmeans.fit_predict(flat_lab)
    centroids_lab = kmeans.cluster_centers_  # (k, 3)

    # Compute cluster weights
    counts = np.bincount(labels, minlength=k)
    weights = counts / n_pixels  # fractions summing to 1

    results: list[ColorMatch] = []
    for i in range(k):
        L, a, b = centroids_lab[i]
        centroid_lab: _LAB = (float(L), float(a), float(b))
        color_id, color_name, hex_val = _nearest_lego_color(centroid_lab)
        results.append(
            ColorMatch(
                color_id=color_id,
                color_name=color_name,
                hex=hex_val,
                cluster_weight=float(weights[i]),
            )
        )

    results.sort(key=lambda c: c.cluster_weight, reverse=True)
    return results


def match_color(rgb_hex: str) -> ColorMatch:
    """Find the nearest LEGO color for a given RGB hex string using Î”E2000.

    Args:
        rgb_hex: 6-character hex string (with or without leading '#'),
                 upper or lowercase, e.g. "F4F4F4" or "#f4f4f4".

    Returns:
        ColorMatch with the nearest LEGO color.
    """
    hex_clean = rgb_hex.lstrip("#").upper()
    input_rgb = _hex_to_rgb255(hex_clean)
    input_lab = _rgb255_to_lab(*input_rgb)
    color_id, color_name, hex_val = _nearest_lego_color(input_lab)
    return ColorMatch(
        color_id=color_id,
        color_name=color_name,
        hex=hex_val,
        cluster_weight=1.0,
    )

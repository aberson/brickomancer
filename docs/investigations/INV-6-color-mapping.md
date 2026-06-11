# INV-6: LEGO Color Mapping

**Question:** How do we extract dominant colors from an input image and map them to the closest available LEGO colors?

---

## Executive Summary

**Stack:** scikit-learn KMeans (k=8) in Lab color space for extraction → basic-colormath ΔE2000 for nearest-LEGO-color matching → Rebrickable colors.csv as the palette source.

**Key findings:**
- LEGO produces ~73-78 active solid colors (as of 2024-2025); ~214 total including retired
- The 4 most-produced colors (Black, White, Light Bluish Gray, Dark Bluish Gray) account for >50% of all LEGO bricks manufactured
- CIE Lab ΔE2000 is clearly superior to RGB Euclidean distance for perceptual color matching
- Rebrickable `colors.csv` (CC0) is the best machine-readable source, with `rgb` hex field

---

## 1. Official LEGO Color Palette

### How many colors exist?

LEGO's active palette as of 2024-2025:
- ~47 solid colors (44 historically stable + 3 added Jan 2024: Reddish Orange, Umber Brown, Sienna Brown)
- ~11-14 transparent/translucent colors
- ~10-15 metallic, pearl, glitter, and satin finishes
- Plus ~130+ retired colors tracked historically (BrickLink documents 214 total)

### Best data source: Rebrickable colors.csv (CC0)

**URL:** `https://cdn.rebrickable.com/media/downloads/colors.csv.gz`

**Schema (8 columns):**
```
id, name, rgb, is_trans, num_parts, num_sets, y1, y2
15, White, F4F4F4, False, 3842, 18741, 1950, 2024
0, Black, 212121, False, 3201, 17943, 1950, 2024
4, Red, B40000, False, 1893, 12905, 1950, 2024
```

Key fields:
- `rgb` — hex string without `#` (e.g. `"F4F4F4"`)
- `is_trans` — boolean; filter `== False` for V1 solid palette
- `num_parts` — proxy for availability breadth (colors with `num_parts > 500` are deeply embedded)
- `num_sets` — proxy for commonness

**License: CC0 — public domain, commercial use fully permitted, no attribution required.**

### Second source: LDraw LDConfig.ldr

**URL:** `https://library.ldraw.org/library/official/LDConfig.ldr`

**Format:**
```
0 !COLOUR White   CODE 15  VALUE #F4F4F4  EDGE #9C9291
0 !COLOUR Black   CODE 0   VALUE #1B2A34  EDGE #255255255
0 !COLOUR Red     CODE 4   VALUE #B40000  EDGE #7D0000
```

Parse: split on whitespace, extract `CODE` → int (LDraw color ID), `VALUE` → `#RRGGBB`.

**Why two sources are needed:** LDraw color IDs and Rebrickable color IDs use different numbering systems. Rebrickable's `colors.csv` includes an `external_ids` field that cross-references LDraw and BrickLink IDs.

**Important caveat:** LDraw RGB values are LEGO's digital approximations and differ from physical ABS Pantone values. RGB is sufficient for algorithmic color matching purposes.

---

## 2. Color Extraction from Images

### Recommended: scikit-learn KMeans

```python
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans
from skimage import color as skcolor

def extract_dominant_colors(image_path: str, k: int = 8) -> list[tuple[int,int,int]]:
    img = Image.open(image_path).convert("RGB")
    img = img.resize((150, 150))          # downsample for speed
    pixels = np.array(img).reshape(-1, 3).astype(float)
    
    # Convert to Lab color space for perceptually balanced clusters
    lab_pixels = skcolor.rgb2lab(pixels.reshape(1, -1, 3) / 255.0).reshape(-1, 3)
    
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(lab_pixels)
    
    # Convert centroids back to RGB
    centroids_rgb = skcolor.lab2rgb(km.cluster_centers_.reshape(1, -1, 3)) * 255
    return [(int(r), int(g), int(b)) for r, g, b in centroids_rgb[0]]
```

**Advantages over color-thief-py (median-cut):**
- Full control over cluster sizes (for weighting dominant colors by coverage)
- Lab space clustering gives perceptually balanced results
- Cluster sizes tell you which color dominates the image

### How many dominant colors to extract?

**k=8** is the practical sweet spot for most LEGO target images:
- k < 4 merges visually distinct regions
- k > 10 produces near-duplicate colors that confuse the LEGO mapper
- Use k=8 and deduplicate LEGO matches (multiple extracted colors may map to the same LEGO color)

---

## 3. Nearest-LEGO-Color Matching

### CIE Lab ΔE2000 wins clearly over RGB Euclidean

**RGB Euclidean distance is inadequate** for perceptual color matching. Equal numerical distances in RGB space correspond to wildly different perceived differences — the encoding is not perceptually uniform.

**CIE Lab ΔE** was specifically designed so equal numerical ΔE distances correspond to equal perceived color differences. For LEGO matching, even ΔE76 (simple Euclidean distance in Lab space) is a major improvement over RGB. **ΔE2000** is the most accurate metric and still computationally cheap for a palette of ~50-200 colors.

### Implementation: basic-colormath

`basic-colormath` is the best option: lightweight, no numpy dependency, 14× faster than python-colormath, uses ΔE CIE 2000 natively.

```python
from basic_colormath import get_delta_e_hex

def build_lego_palette(colors_csv_path: str) -> dict[str, str]:
    """Returns {lego_color_name: hex_string} for non-transparent colors."""
    import csv
    palette = {}
    with open(colors_csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['is_trans'] == 'False':
                palette[row['name']] = row['rgb']
    return palette

def find_nearest_lego_color(rgb: tuple[int,int,int], palette: dict[str, str]) -> str:
    hex_query = "%02X%02X%02X" % rgb
    return min(
        palette.items(),
        key=lambda item: get_delta_e_hex(hex_query, item[1])
    )[0]
```

### Color extraction → LEGO matching pipeline

```
Input image → resize to 150×150 → pixel array
  → RGB→Lab conversion (skimage)
  → KMeans(k=8) clustering in Lab space
  → Cluster centroids → Lab→RGB conversion
  → For each centroid: compute ΔE2000 vs every LEGO color in palette
  → Return [(lego_color_name, lego_hex, cluster_weight), ...] sorted by cluster size
```

---

## 4. Parts Availability by Color

### Proxy approach (recommended for V1)

Rather than hitting the Rebrickable API per-color per-part, use the `num_parts` column from `colors.csv` as the availability proxy:
- Colors with `num_parts > 500` are deeply embedded in LEGO's catalog
- Colors with `num_parts > 1000` are essentially guaranteed to include standard bricks (2×2, 2×4, plates)

### Rebrickable API (V2)

- `GET /api/v3/lego/colors/{color_id}/parts/` — lists all parts available in a given color
- `GET /api/v3/lego/parts/{part_num}/colors/` — lists all colors a specific part exists in

---

## 5. Safe V1 Color Palette (28 Colors)

Colors reliably available in standard brick sizes through Pick-a-Brick, BrickLink, and major set supply. Selected based on: Pick-a-Brick catalog confirmation for 2024-2025, high `num_parts` counts (>500), visually diverse gamut.

| # | Name | Rebrickable ID | Hex RGB | Notes |
|---|---|---|---|---|
| 1 | Black | 0 | 1B2A34 | Top-4 most produced |
| 2 | White | 15 | F4F4F4 | Top-4 most produced |
| 3 | Light Bluish Gray | 71 | 969696 | Top-4 most produced |
| 4 | Dark Bluish Gray | 72 | 646464 | Top-4 most produced |
| 5 | Red | 4 | B40000 | Classic, ubiquitous |
| 6 | Blue | 1 | 1E5AA8 | Classic, ubiquitous |
| 7 | Yellow | 14 | FAC80A | Classic, ubiquitous |
| 8 | Green | 2 | 00852B | Classic, ubiquitous |
| 9 | Orange | 25 | D67923 | Widely available |
| 10 | Dark Red | 320 | 6D0001 | Common in Technic/City |
| 11 | Dark Blue | 272 | 0A3463 | Common in many sets |
| 12 | Dark Green | 288 | 184632 | Moderate availability |
| 13 | Lime (Yellow-Green) | 27 | A5CA18 | PAB available |
| 14 | Bright Green | 10 | 58AB41 | PAB available |
| 15 | Tan | 19 | B0A06F | Very common |
| 16 | Dark Tan | 28 | 897D62 | Common |
| 17 | Reddish Brown | 70 | 5F3109 | Very common |
| 18 | Brown | 6 | 543324 | Older; still available |
| 19 | Medium Blue | 73 | 7396C8 | Friends/City sets |
| 20 | Sand Green | 151 | 7D9C8B | Popular MOC color |
| 21 | Olive Green | 330 | 9B9A5A | Popular MOC color |
| 22 | Medium Azure | 322 | 36AEBF | Widely in Friends/PAB |
| 23 | Bright Light Blue | 212 | 9DC3F7 | PAB available |
| 24 | Bright Light Orange | 191 | FCAC00 | PAB available |
| 25 | Bright Light Yellow | 226 | FFEC6C | PAB available |
| 26 | Lavender | 31 | CDA4DE | PAB confirmed |
| 27 | Medium Lavender | 30 | A06EB9 | PAB confirmed |
| 28 | Nougat | 18 | BB805A | Very common (skin tone) |

**The four most produced colors** (Black, White, Light Bluish Gray, Dark Bluish Gray) alone represent >50% of all LEGO bricks manufactured — always include these.

**Exclude for V1:** Metallic/chrome finishes, transparent colors, glitter variants, recently introduced colors (added 2024-2026) — availability in common brick sizes not yet guaranteed.

---

## 6. Dependencies

```
Pillow >= 10.0          # image loading
numpy >= 1.24           # pixel array operations
scikit-learn >= 1.3     # KMeans clustering
scikit-image >= 0.21    # rgb2lab / lab2rgb conversion
basic-colormath >= 0.3  # ΔE CIE 2000, fast, lightweight
```

---

## Sources

- [Rebrickable Colors](https://rebrickable.com/colors/)
- [Rebrickable Downloads](https://rebrickable.com/downloads/)
- [LDraw Colour Definition Reference](https://www.ldraw.org/article/547.html)
- [LDraw Colour Definition Extension](https://www.ldraw.org/article/299.html)
- [BrickLink Color Guide](https://v2.bricklink.com/en-us/catalog/color-guide)
- [The LEGO Color Palette: 2023 Edition — BrickNerd](https://bricknerd.com/home/the-lego-color-palette-2023-edition-1-24-23)
- [LEGO Color Reference — Brick Architect](https://brickarchitect.com/color/)
- [Perceptual Color Distance — antimatter15](https://antimatter15.com/wp/2014/05/perceptual-color-distance-and-rgb-and-lab/)
- [basic-colormath on PyPI](https://pypi.org/project/basic-colormath/)
- [CIELAB color space — Wikipedia](https://en.wikipedia.org/wiki/CIELAB_color_space)
- [New Elementary — Pick a Brick March 2024](https://www.newelementary.com/2024/03/lego-pick-brick-new-elements-added-in.html)
- [Rebrickable Colors CSV columns forum](https://forum.rebrickable.com/t/colors-is-now-8-columns/169551)

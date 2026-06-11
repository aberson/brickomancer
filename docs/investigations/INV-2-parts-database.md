# INV-2: Parts Database & API Options

**Question:** What data sources exist for LEGO parts, colors, dimensions, and set inventories — and which are usable for Brickomancer?

---

## Executive Summary

No single source covers all needs. **Rebrickable** is the clear V1 primary: free, REST, Python-friendly, CC0-licensed bulk downloads, covers parts/colors/sets/images with an `rgb` hex field. **LDraw** is the only freely-licensed source for physical dimensions. **BrickLink** is the richest marketplace data source but requires OAuth 1.0 and seller registration. **BrickOwl** is marketplace-focused with case-by-case access approval. **LEGO has no public API.**

---

## Rebrickable API

**What data is available:**

| Data type | Available | Notes |
|---|---|---|
| Parts (name, number, category) | Yes | `/lego/parts/`, `/lego/parts/{part_num}/` |
| Colors (with RGB hex) | Yes | `/lego/colors/` — field `rgb` contains hex (e.g. `"F2CD37"`) |
| Part images | Yes | `part_img_url` field per part; `element_img_url` per element+color combo |
| Set inventories | Yes | `/lego/sets/{set_num}/parts/` |
| Part-to-set mapping | Yes | `/lego/parts/{part_num}/sets/` |
| Physical dimensions (mm) | **No** | Not in the database; BrickLink has it but prohibits reuse |
| Pricing | No | |

**Summary numbers:** 63,345 parts, 27,069 sets, 189,973 MOCs (as of mid-2026).

**Auth:** API key in `Authorization: key <key>` header. Free to register.

**Rate limits:** ~1 request/sec for free accounts. HTTP 429 on violation.

**Bulk download (recommended):** CSV exports at `rebrickable.com/downloads/` — includes `colors.csv`, `parts.csv`, `inventories.csv`, `inventory_parts.csv`, `sets.csv`. Updated daily. **License: CC0 (public domain — commercial use fully permitted, no attribution required).**

**Python:** `pyrebrickable` on GitHub (rienafairefr). Alternatively, direct `requests` calls against the REST API are simple.

**Brickomancer use:** Primary data source for V1. Download CC0 CSVs locally (no rate limits, no auth). Use the REST API only for user-specific operations.

---

## BrickLink API

**What data is available:**

| Data type | Available | Notes |
|---|---|---|
| Catalog items (parts, sets, minifigs) | Yes | CatalogMethod endpoints |
| Known colors per item | Yes | |
| Item images by color | Yes | Image URL per item+color |
| Physical dimensions | Yes (web UI only) | ToS prohibit reuse by third parties |
| Price guides | Yes | Current/6-month/all-time sales data |
| Set inventories | Yes | |

**Auth:** OAuth 1.0 — requires Consumer Key, Consumer Secret, Token Value, Token Secret. Token Value/Secret are **per-IP-address**, making cloud deployments cumbersome. **Strong indication that a seller account is required.**

**Commercial use / license:** API Terms of Use explicitly prohibit reusing catalog data outside of BrickLink-approved contexts. Physical dimension data blocked for third-party reuse.

**Brickomancer use:** Not recommended. High friction for a non-seller developer. Dimension data blocked by ToS.

---

## LDraw Parts Library

**What data is available:**

| Data type | Available | Notes |
|---|---|---|
| Part geometry (.dat files) | Yes | 45,529 files in library |
| Physical dimensions | Yes | Derivable from geometry: 1 LDU = 0.4 mm exactly |
| Color definitions with RGB hex | Yes | `LDConfig.ldr` — `!COLOUR name CODE x VALUE #RRGGBB EDGE e` |
| Part images | No | Geometry only; rendering required |
| Set inventories | No | |

**How dimensions work:** Each `.dat` file encodes part geometry in LDraw Units. 1 LDU = 0.4 mm (1 stud pitch = 20 LDU = 8 mm). Bounding box can be computed by parsing vertex coordinates. A community tool (jncraton, MIT license) already extracted a CSV of bounding-box dimensions for 4,000+ Rebrickable parts from LDraw geometry.

**How colors work:** `LDConfig.ldr` is the authoritative color file. Format: `0 !COLOUR Black CODE 0 VALUE #1B2A34 EDGE #255255255`. Explicitly uses LEGO official RGB values.

**Access:** Single ZIP download from `https://library.ldraw.org/library/updates/complete.zip`. No auth. Offline.

**License:** Most official parts are under **CC BY 4.0** (commercial use permitted with attribution).

**Python tooling:** `pyldraw` (michaelgale, GitHub) — actively maintained.

**Brickomancer use:** Best and only freely-licensed source for physical dimensions. Parse `LDConfig.ldr` at startup for authoritative color table. Use the community-extracted dimension CSV for part sizes.

---

## BrickOwl API

**What data is available:** Parts catalog (approval required), colors, images, price history.

**Auth:** API key + contact form approval (case-by-case).

**Brickomancer use:** Not recommended for V1. Approval process and no SDK make it unreliable.

---

## LEGO Official API

**No public API exists.** LEGO does not expose a developer-accessible API for its parts database, color catalog, or set inventories.

---

## Authoritative LEGO Color Palette

Two authoritative machine-readable sources:

**LDConfig.ldr (LDraw)** — most authoritative freely-available machine-readable color file. Format: `0 !COLOUR <name> CODE <ldraw_id> VALUE #<RRGGBB> EDGE #<RRGGBB> [ALPHA <0-255>]`. Download: `https://library.ldraw.org/library/official/LDConfig.ldr`. Covers ~400+ colors. CC BY 4.0.

**Rebrickable `/lego/colors/` and `colors.csv`** — maps Rebrickable color IDs to `rgb` hex field. CC0. The `colors.csv` `external_ids` field cross-references LDraw and BrickLink IDs.

**Why two are needed:** LDraw color IDs and Rebrickable color IDs use different numbering systems.

---

## Comparison Table

| | Rebrickable API | Rebrickable CSV | BrickLink API | LDraw Library | BrickOwl API |
|---|---|---|---|---|---|
| **Parts catalog** | Yes | Yes | Yes | Yes (geometry) | Yes (approval req'd) |
| **Colors + RGB hex** | Yes (`rgb` field) | Yes (CC0) | Yes | Yes (LDConfig.ldr) | Yes (color_list) |
| **Part images** | Yes (URL field) | No | Yes (URL) | No | Partial |
| **Set inventories** | Yes | Yes | Yes | No | Unclear |
| **Physical dimensions** | No | No | Yes (ToS blocks reuse) | Yes (parse geometry) | No |
| **Pricing** | No | No | Yes | No | Yes (approval) |
| **Auth complexity** | API key | None | OAuth 1.0 + per-IP | None (download) | API key + approval |
| **License** | Unspecified (free use) | CC0 | Restrictive ToS | CC BY 4.0 | Restrictive ToS |
| **Python SDK** | pyrebrickable | pandas/csv | bricklink-py (AGPLv3) | pyldraw | None |

---

## V1 Recommendation

**Primary: Rebrickable bulk CSV downloads (CC0)**

Download `colors.csv`, `parts.csv`, `sets.csv`, `inventory_parts.csv` via `scripts/download_data.py` into `data/rebrickable/`. This gives full part catalog, RGB hex colors, complete set inventories, part image URLs, zero rate-limit concerns, no auth, commercial use permitted.

**Supplement: LDraw LDConfig.ldr for color authority + dimension data**

- Parse `LDConfig.ldr` at startup to build a local color table with `CODE → VALUE (#hex)` mapping
- Use the community-extracted dimension CSV for physical dimension lookups

**Skip for V1:** BrickLink (OAuth 1.0 + seller gate + restrictive ToS), BrickOwl (approval process + no SDK).

---

## Download URLs

```python
REBRICKABLE_DOWNLOADS = [
    "https://cdn.rebrickable.com/media/downloads/colors.csv.gz",
    "https://cdn.rebrickable.com/media/downloads/parts.csv.gz",
    "https://cdn.rebrickable.com/media/downloads/inventory_parts.csv.gz",
    "https://cdn.rebrickable.com/media/downloads/sets.csv.gz",
]
LDRAW_CONFIG = "https://library.ldraw.org/library/official/LDConfig.ldr"
```

---

## Sources

- [Rebrickable API docs](https://rebrickable.com/api/)
- [Rebrickable downloads (CC0 CSVs)](https://rebrickable.com/downloads/)
- [LDraw Colour Definition Reference](https://www.ldraw.org/article/547.html)
- [LDraw !COLOUR language extension](https://www.ldraw.org/article/299.html)
- [pyldraw Python library](https://github.com/michaelgale/pyldraw)
- [BrickOwl API docs](https://www.brickowl.com/api_docs)
- [Rebrickable colors CSV columns forum](https://forum.rebrickable.com/t/colors-is-now-8-columns/169551)

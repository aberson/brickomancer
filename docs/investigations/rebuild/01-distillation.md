# Distillation — What to Keep From v1

Precise inventory of reusable assets for the rebuild. Cite file paths. This is the salvage
list; anything not here is a candidate to drop.

## 1. Inter-module contracts worth preserving

These are hard-won and should survive verbatim. Source of truth: `src/brickomancer/models/`.

- **`suggestion_id` format:** `<uuid>_<tier_index>` (0=compact, 1=standard, 2=detailed). Producer
  is `suggestion_service`; consumer is `routers/generate.py` (reconstructs
  `tmp/<uuid>/suggestion_<tier_index>.ldr`). Any change requires updating both ends.
- **`BrickPlacement`** ([brick.py:38-47](../../../src/brickomancer/models/brick.py#L38-L47)):
  `part_id: str, color_id: int, x: int, y: int, z: int, width: int, length: int`.
- **`ColorMatch`** ([brick.py:50-57](../../../src/brickomancer/models/brick.py#L50-L57)):
  `color_id: int, color_name: str, hex: str, cluster_weight: float`.
- **Voxel grid convention:** `(X, Y, Z)` bool array; **Y-up**, Y=0 is ground, increasing Y is up;
  `True` = occupied. Flows through packer → ldraw_writer.
- **LDraw coordinate constants** ([ldraw_writer.py:39-42](../../../src/brickomancer/services/ldraw_writer.py#L39-L42)):
  `_STUD_LDU = 20`, `_LAYER_LDU = 24`, `_TILE_HEIGHT_LDU = 8`. Mapping:
  `x_ldu = x*20 + (width-1)*10`, `y_ldu = y*-24` (LDraw Y is inverted), `z_ldu = z*20 + (length-1)*10`.
  Tiles sit on studs of the layer below (`y*-24 + 16`).
- **API route contract:** `POST /api/generate/from-image|from-text|instructions`,
  `GET /api/colors|status`. `GenerateResponse{ suggestions: [Suggestion{ id, tier, preview_url,
  parts_count, parts_list }] }`. See `docs/master_plan.md` §6.
- **Brick vocabulary single source of truth** ([brick.py:10-12](../../../src/brickomancer/models/brick.py#L10-L12)):
  `BRICK_TYPES` (largest-first), `BRICK_PART_IDS`, `TILE_PART_IDS`.

Also captured in the `feedback_arch_contracts` memory.

## 2. Tests worth keeping (the regression spine)

| Test file | Lines | Verdict | Why |
|---|---|---|---|
| `test_brick_packer.py` | 475 | **KEEP ~95%** | Masonry interlocking, connectivity-repair invariants, "every brick at y>0 connects to y-1", step sequencing — genuine domain knowledge. |
| `test_color_service.py` | 221 | **KEEP ~100%** | ΔE2000 matching, cluster-weight normalization, hex-parsing robustness. |
| `test_data_service.py` | 201 | **KEEP ~95%** | LDConfig > CSV priority; **color IDs > 511 must not be returned** (LDView fails on them). |
| `test_instruction_service.py` | 178 | **KEEP ~100%** | LPub3D subprocess + `ToolUnavailableError` graceful degradation. |
| `test_main.py` | 274 | **KEEP ~90%** | `/api/status` health checks, error→503 promotion, `suggestion_id` validation. |
| `test_image_pipeline.py` | 273 | **RE-EVAL** | Tests the silhouette path that is being replaced; keep the voxel-shape/contract assertions, drop dome-specific ones. |
| `test_suggestion_service.py` | 528 | **KEEP** | 3-tier downsampling contract + `suggestion_id` format. |
| `test_piece_detector.py` | 388 | **KEEP** if piece detection survives | Claude subprocess + JSON parse + merge dedup. |
| `test_text_pipeline.py` | 406 | **RE-EVAL** | Tests Llama-1B primitive path being replaced; keep voxel-contract tests, drop archetype-primitive ones. |
| `tests/harness/*` | ~1500 | **RE-EVAL** | Keep only if the harness is rebuilt (it is — but redesigned, so expect to rewrite judge/applier tests). |

## 3. Hard-won fixes encoded in the code

Each is a problem the rebuild should not re-learn the hard way.

**Coordinate / axis**
- **Y-up → LDraw Y-negation** + tile Y offset — early builds placed bricks upside-down.
  `ldraw_writer._to_ldu`.
- **Brick-center LDU offset** (`+(width-1)*10`) — multi-stud bricks must center correctly.

**Packing** (`brick_packer.py`)
- **Per-Z-row masonry pre-pass** (odd layers seed a 1×1 at the leftmost stud) — staggers seams,
  prevents vertical fault planes.
- **Connectivity repair = replacement, not addition** — output is `filtered + bridge_bricks`
  where `filtered` excludes removed indices. Earlier code appended bridges *alongside* floating
  bricks, leaving them floating. (Critical invariant; in `feedback_arch_contracts`.)
- **Isolated-pillar removal + thin-column bracing + floor support + surface tiles** — the four
  repair passes. NOTE: the rebuild replaces these with a connectivity-graph packer
  (see [03](03-better-approaches.md) §2); they encode *what good output looks like*, not *how* to get it.

**Voxelization / color**
- **`method='subdivide'`** in trimesh voxelization — avoids the optional `rtree` dependency.
- **Subject-color filter `alpha > 10`** ([color_service.py:114](../../../src/brickomancer/services/color_service.py#L114)) —
  excludes rembg edge-noise from KMeans.
- **Lab-space clustering + ΔE2000** — perceptually uniform color matching.

**Subprocess integration** (`subprocess_utils.py`)
- **`claude -p` does NOT support `--image`** — embed the absolute path in the prompt + "Use your
  Read tool to view this image." No `--output-format json` (CLI wraps it in an envelope).
- **LDView needs `-LDrawDir=<path>`** even when bundled, or parts render solid black.
- **LDView can exit 0 without writing the PNG** — always check `Path(output_png).exists()`.
- **LPub3D has no `-o` flag** — invoke `LPub3D -x -pe pdf <abs_ldr>` from the install dir; PDF
  lands next to the input as `<basename>_<dpi>_DPI.pdf`; glob for `*.pdf`.
- **`CLAUDE_CODE_OAUTH_TOKEN`**, never `ANTHROPIC_API_KEY`. Bash tool does not inherit Windows
  user env vars — launch from PowerShell.

## 4. Reference data + external-tool knowledge

| Asset | Source | License | Keep? |
|---|---|---|---|
| `data/ldraw/LDConfig.ldr` | ldraw.org (403 as of 2026-06; copy from LPub3D if missing) | CC BY 4.0 | **Yes** — authoritative color codes 0-511; required for valid LDraw color. |
| `data/ldraw/dimensions.csv` | jncraton (community) | MIT | **Yes** — part bounding boxes in LDU. |
| `data/rebrickable/colors.csv` | Rebrickable CDN | CC0 | **Yes** — fallback palette; IDs > 511 don't render. |
| `data/rebrickable/parts.csv` | Rebrickable CDN | CC0 | Yes — parts-list names. |
| `scripts/download_data.py` | — | — | **Yes** — the fetch script. |
| **28-color safe V1 palette** | INV-6 (master_plan §12.6) | — | **Yes** — colors reliably available in real brick sizes. |

External tool flags (LDView snapshot args, LPub3D headless invocation, llama-server
OpenAI-compatible endpoint at `:8080`, rembg `[cpu]` for CUDA 11.8) are all documented in the
master plan §10 and `subprocess_utils.py`. These took real effort to discover — preserve them.

## 5. Documentation assets

| Doc | Keep for rebuild? |
|---|---|
| `docs/master_plan.md` | **Yes** — full v1 architecture, API contract, LDraw appendix, safe palette. The single best reference. |
| `docs/investigations/INV-1` (competitor audit) | Yes (reference) |
| `INV-2` (parts database) | Maybe — re-derivable from Rebrickable schema |
| `INV-3` (image→3D) | Yes (reference) — but its TripoSR conclusion is superseded; see [03](03-better-approaches.md) |
| `INV-4` (voxelization/packing) | **Yes** — packing-algorithm rationale |
| `INV-5` (instruction generation) | **Yes** — LDView/LPub3D CLI discovery |
| `INV-6` (color mapping) | **Yes** — ΔE2000 + LDConfig-vs-Rebrickable rationale |
| `INV-7` (test/shape quality) | **Yes** — root-cause of shape-fidelity issues; feeds the rebuild |
| `docs/shape-quality-plan.md` | Partial — Steps 1-2 done; Steps 3-4 (rembg model swap, OR-pool) subsumed by the 3D-model replacement |
| `docs/harness-plan.md` | Reference only — the harness is being redesigned |

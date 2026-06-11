# Brickomancer — Master Plan

## 1. What This Is

Brickomancer is a local-first web tool that transforms a photo of a real-world object (a birthday cake, a bear, a house) or a natural language description into LEGO build instructions. Given an input, it generates 3–5 build suggestions — each with a rendered 3D preview and a parts list — then produces a downloadable step-by-step instruction book in the style of official LEGO manuals for the selected suggestion. Optionally, the user can photograph their available LEGO pieces and Brickomancer will identify and incorporate those parts as build constraints.

Built for personal use as a local Python/React web app (V1), with a clean REST API designed for migration to a phone or desktop frontend in a future version.

## 2. Stack

| Layer | Tool | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Workspace standard; clean REST API separates frontend from server logic |
| Package manager | uv | Workspace standard |
| Frontend | React 18 + Vite | Matches Alpha4Gate stack; swappable for React Native / Electron later |
| Image → 3D mesh | TripoSR (MIT, Stability AI) | Single-image watertight mesh; handles back geometry; runs on local CUDA GPU |
| Background removal | rembg | CPU-viable; required pre-TripoSR for clean object isolation |
| Voxelization | trimesh | `mesh.voxelized(pitch=8.0).fill()` → numpy bool grid at LEGO stud resolution |
| Text → shape | Llama 3.2-1B via llama-server (llama.cpp) | Local inference, zero API cost; matches void_furnace llama.cpp adapter pattern |
| Piece detection | Claude (claude-sonnet-4-6) via CLAUDE_CODE_OAUTH_TOKEN subprocess | Strong vision; no API key billing; model abstracted for future swap to local LLaVA |
| Color matching | scikit-learn + scikit-image + basic-colormath | KMeans k=8 in Lab space; ΔE2000 vs LEGO palette; perceptually accurate |
| Parts database | Rebrickable CC0 CSVs + LDraw LDConfig.ldr | Free, offline, CC0-licensed; no runtime API dependency |
| 3D rendering | LDView (headless CLI) | Per-suggestion PNG preview from LDraw; active maintenance; BSD license |
| Instruction PDF | LPub3D (headless CLI) | Publication-quality paginated instruction book; GPL v3; headless confirmed |
| LDraw output | Python string formatting | LDraw is plain text; no library needed for V1 |
| Testing | pytest + ruff + mypy | Workspace standard |

## 3. Data Store

**No database.** All session state is ephemeral — held in memory for the duration of a request. Intermediate files are written to a per-request temp directory (`tmp/<uuid>/`) and deleted after the response is sent.

**Static reference data** — downloaded once during project setup via `scripts/download_data.py`, stored in `data/`:

| File | Source | License | Contents |
|---|---|---|---|
| `data/rebrickable/colors.csv` | `https://cdn.rebrickable.com/media/downloads/colors.csv.gz` | CC0 | 224 colors: id, name, rgb (hex), is_trans, num_parts |
| `data/rebrickable/parts.csv` | `https://cdn.rebrickable.com/media/downloads/parts.csv.gz` | CC0 | 63K parts: part_num, name, part_cat_id |
| `data/rebrickable/inventory_parts.csv` | `https://cdn.rebrickable.com/media/downloads/inventory_parts.csv.gz` | CC0 | Set-to-part mappings |
| `data/ldraw/LDConfig.ldr` | `https://library.ldraw.org/library/official/LDConfig.ldr` | CC BY 4.0 | Authoritative LEGO color definitions with official RGB hex |
| `data/ldraw/dimensions.csv` | Community-extracted (jncraton, MIT) | MIT | Bounding box dimensions for 4K+ parts in LDraw units |

**Per-request scratch** (`tmp/<uuid>/`, cleaned up after response):

```
tmp/<uuid>/
  input.jpg                  # uploaded target photo
  pieces_0.jpg               # piece photos (one per upload)
  pieces_N.jpg
  mesh.obj                   # TripoSR output
  mesh_scaled.obj            # trimesh scaled to real-world dimensions
  voxels.npy                 # numpy bool array (X, Y, Z)
  suggestion_0.ldr           # LDraw file per suggestion
  suggestion_0_preview.png   # LDView render
  suggestion_1.ldr
  suggestion_1_preview.png
  ...
  instructions.pdf           # LPub3D output for selected suggestion
```

## 4. Pipeline

### 4.1 Input Path A — Photo of Target Object

1. User uploads photo (JPG/PNG)
2. `rembg` removes background → transparent PNG
3. TripoSR generates watertight OBJ mesh (~0.5–2s on CUDA GPU)
4. User confirms approximate real-world height in studs (default: 10); trimesh scales mesh accordingly
5. `mesh.voxelized(pitch=8.0, method='ray').fill()` → `numpy.ndarray[bool, (X, Y, Z)]`

### 4.2 Input Path B — Natural Language Description

1. User types description (e.g. "big blue birthday cake")
2. Llama 3.2-1B via llama-server (llama.cpp, port 8080) extracts structured shape parameters:
   ```json
   {"archetype": "cylinder", "height_studs": 8, "radius_studs": 5,
    "colors": ["white", "yellow", "light_blue"]}
   ```
3. Python builds primitive mesh from archetype: `trimesh.creation.cylinder(radius=r*0.008, height=h*0.0096)`
4. `mesh.voxelized(pitch=8.0).fill()` → same numpy bool format as Path A

### 4.3 Piece Detection (Optional)

1. User uploads 1–N photos of their LEGO piece pile
2. Each photo passed to Claude subprocess (CLAUDE_CODE_OAUTH_TOKEN, not API key):
   ```
   claude -p "<prompt>" --image <path>
   ```
   Prompt: see Appendix §12.4. Output: JSON list of `{part_id, qty, color}`.
3. Multi-photo results merged with deduplication (sum quantities for duplicate part_ids)
4. Part inventory stored in memory; passed to suggestion generation as soft constraint (prefer available parts; V1 does not hard-constrain)

### 4.4 Color Mapping

1. **Image input:** resize to 150×150, convert to Lab color space, `KMeans(n_clusters=8).fit(pixels)` → cluster centroids → hex strings
2. **Text input:** parse color names from Llama shape parameters (e.g. `["white", "yellow"]`) → look up hex from `colors.csv` by name
3. For each extracted color: compute ΔE2000 (`basic-colormath.get_delta_e_hex()`) against every non-transparent LEGO color in `colors.csv`
4. Return `list[(lego_color_id, lego_color_name, hex, cluster_weight)]` sorted by cluster size

### 4.5 Suggestion Generation

From a voxel grid + color palette, generate 3 build suggestions at different complexity tiers:

| Tier | Description | Approx brick count |
|---|---|---|
| Compact | Voxel grid downsampled 2× | 20–50 bricks |
| Standard | Full stud resolution | 50–200 bricks |
| Detailed | Full stud resolution + plate-height sub-layers | 200–500 bricks |

For each tier:
1. Run brick packing algorithm (§4.6) on the (optionally downsampled) voxel grid
2. Apply color assignments from §4.4 (dominant color per Y-layer band)
3. Write LDraw file (§4.7)
4. Call LDView headless: `LDView suggestion_N.ldr -SaveSnapshot=suggestion_N_preview.png -SaveWidth=800 -SaveHeight=600 -SaveZoomToFit=1 -AutoCrop=1`
5. Extract parts list: `{part_id: {color_name: qty}}` from brick placement list

### 4.6 Brick Packing Algorithm

**Input:** `grid: np.ndarray[bool, (X, Y, Z)]`

**Process** (layer-by-layer, Y=0 is ground, increasing Y is up):

```
BRICK_TYPES = [(2,4), (2,3), (2,2), (1,4), (1,3), (1,2), (1,1)]  # sorted largest-first

for layer_y in range(grid.shape[1]):
    bitmap = grid[:, layer_y, :]         # 2D occupancy (X, Z)
    unassigned = {(x,z) for x,z in occupied cells}
    scan_offset_x = layer_y % 2          # masonry: alternate scan start by 1 stud

    for x, z in raster_order(unassigned, offset=scan_offset_x):
        for bw, bl in BRICK_TYPES:
            if fits(bitmap, unassigned, x, z, bw, bl):
                place BrickPlacement(part_id=lookup(bw,bl), x=x, y=layer_y, z=z)
                unassigned -= footprint(x, z, bw, bl)
                break

    # Interlocking check (layer_y > 0)
    for brick B at layer_y:
        if not any brick at layer_y-1 shares ≥1 stud with B:
            split B into smaller bricks straddling a boundary below
```

**Connectivity repair** (post all layers):
- Build adjacency graph: nodes = bricks, edges = shared stud connections
- Find subgraphs not transitively connected to layer 0
- Attempt 1×1 or 1×2 bridge insertion; if impossible, flag zone as "floating"

**Output:** `list[BrickPlacement]`

```python
@dataclass
class BrickPlacement:
    part_id: str      # e.g. "3001" for 2×4 brick
    color_id: int     # LDraw color code (from §4.4)
    x: int            # stud grid X (0-indexed)
    y: int            # layer index (0 = ground)
    z: int            # stud grid Z (0-indexed)
    width: int        # studs in X direction
    length: int       # studs in Z direction
```

### 4.7 LDraw File Format

LDraw is plain text. Each brick placement becomes one Type 1 line:

```
1 <color_id> <x_ldu> <y_ldu> <z_ldu>  <rot_3x3>  <part>.dat
```

Coordinate conversion (1 stud = 20 LDU; 1 brick height = 24 LDU; LDraw Y inverted):
- `x_ldu = placement.x * 20 + (placement.width - 1) * 10`  (center offset)
- `y_ldu = -(placement.y * 24)`
- `z_ldu = placement.z * 20 + (placement.length - 1) * 10`  (center offset)
- Identity rotation: `1 0 0  0 1 0  0 0 1`

Step sequencing: sort bricks by `y` ascending; group into batches of 8; insert `0 STEP` after each batch.

File header:
```
0 Brickomancer — <tier> suggestion
0 !LEOCAD MODEL DESCRIPTION Generated by Brickomancer V1
```

### 4.8 Instruction Generation

1. User selects suggestion N from the gallery
2. `suggestion_N.ldr` already on disk (from §4.5)
3. Call LPub3D headless:
   ```
   lpub3d -pdf -o tmp/<uuid>/ suggestion_N.ldr
   ```
4. Output: `tmp/<uuid>/suggestion_N.pdf`
5. Serve as `application/pdf` file download response

## 5. Modules

```
src/brickomancer/
  main.py                    # FastAPI app init, CORS, startup data loading, /tmp cleanup
  routers/
    generate.py              # POST /api/generate/from-image, /from-text, /instructions
    info.py                  # GET /api/colors, GET /api/status
  services/
    data_service.py          # Loads Rebrickable CSVs + LDConfig.ldr at startup
                             # Exposes: get_color(id), get_part(num), list_colors()
    color_service.py         # extract_colors(image_path) → list[ColorMatch]
                             # match_color(rgb_hex) → ColorMatch via ΔE2000
    image_pipeline.py        # run_triposr(image_path) → obj_path
                             # voxelize(mesh_path, pitch, height_studs) → np.ndarray
    text_pipeline.py         # parse_shape(description) → ShapeParams via llama-server
                             # build_primitive_mesh(params) → obj_path
    brick_packer.py          # pack(grid, brick_set) → list[BrickPlacement]
                             # interlocking_check(placements, layer) → list[BrickPlacement]
                             # connectivity_repair(placements) → list[BrickPlacement]
    ldraw_writer.py          # write_ldr(placements, output_path, tier_name) → path
                             # sequence_steps(placements, bricks_per_step=8) → list[list]
    piece_detector.py        # detect_pieces(image_paths) → list[PieceCount]
                             # merge_piece_lists(lists) → list[PieceCount]
    suggestion_service.py    # generate_suggestions(grid, colors, piece_inventory)
                             #   → list[Suggestion]
    instruction_service.py   # generate_pdf(ldr_path, output_dir) → pdf_path
  models/
    schemas.py               # Pydantic: GenerateImageRequest, GenerateTextRequest,
                             # Suggestion, PartCount, InstructionsRequest, GenerateResponse
    brick.py                 # BrickPlacement, BrickType, ColorMatch, ShapeParams, PieceCount
  utils/
    temp_dir.py              # Context manager: creates tmp/<uuid>/, cleans up on exit
    subprocess_utils.py      # run_claude_subprocess(prompt, image_path) → str
                             # run_ldview(ldr_path, output_png) → None
                             # run_lpub3d(ldr_path, output_dir) → pdf_path

frontend/src/
  components/
    WorkflowStepper.tsx      # Top-level step manager (1–4)
    InputStep.tsx            # Step 1: image upload toggle / text textarea
    PiecesStep.tsx           # Step 2: multi-photo upload + skip button
    SuggestionsStep.tsx      # Step 3: gallery cards (preview, tier badge, parts count)
    InstructionsStep.tsx     # Step 4: spinner → PDF download button
  hooks/
    useGenerate.ts           # Fetch wrapper for POST /api/generate/*
  types.ts                   # TypeScript types matching Pydantic schemas
  App.tsx
  main.tsx
```

## 6. API Route Contract

| Method | Path | Content-Type | Body | Response |
|---|---|---|---|---|
| POST | `/api/generate/from-image` | `multipart/form-data` | `image` (file), `piece_images[]` (files, optional), `height_studs` (int, default 10) | `GenerateResponse` |
| POST | `/api/generate/from-text` | `application/json` | `{description: str, piece_images: [base64], height_studs: int}` | `GenerateResponse` |
| POST | `/api/generate/instructions` | `application/json` | `{suggestion_id: str}` | `application/pdf` file |
| GET | `/api/colors` | — | — | `[{id, name, hex, is_trans}]` |
| GET | `/api/status` | — | — | `{status, llama_server_ok, ldview_ok, lpub3d_ok}` |

`GenerateResponse` shape:
```json
{
  "suggestions": [
    {
      "id": "<uuid>",
      "tier": "compact|standard|detailed",
      "preview_url": "/tmp/<uuid>/suggestion_0_preview.png",
      "parts_count": 47,
      "parts_list": [
        {"part_id": "3001", "color_name": "Red", "color_hex": "B40000", "qty": 4}
      ]
    }
  ]
}
```

## 7. Project Structure

```
brickomancer/
  src/
    brickomancer/              # Python backend package
      main.py
      routers/
        generate.py
        info.py
      services/
        data_service.py
        color_service.py
        image_pipeline.py
        text_pipeline.py
        brick_packer.py
        ldraw_writer.py
        piece_detector.py
        suggestion_service.py
        instruction_service.py
      models/
        schemas.py
        brick.py
      utils/
        temp_dir.py
        subprocess_utils.py
  frontend/
    src/
      components/
        WorkflowStepper.tsx
        InputStep.tsx
        PiecesStep.tsx
        SuggestionsStep.tsx
        InstructionsStep.tsx
      hooks/
        useGenerate.ts
      types.ts
      App.tsx
      main.tsx
    index.html
    vite.config.ts
    package.json
    tsconfig.json
  data/
    rebrickable/               # CC0 CSVs (gitignored; re-downloaded on setup)
      colors.csv
      parts.csv
      inventory_parts.csv
    ldraw/
      LDConfig.ldr             # Authoritative color definitions
      dimensions.csv           # Community part bounding boxes (MIT, 4K+ parts)
  tmp/                         # Per-request scratch (gitignored)
  tests/
    test_color_service.py
    test_brick_packer.py
    test_data_service.py
    test_image_pipeline.py
    test_text_pipeline.py
    test_ldraw_writer.py
    integration/
      test_smoke.py
      fixtures/
        cake.jpg               # Birthday cake photo (planning session reference)
        lego_cake.jpeg         # LEGO cake photo (piece detection reference)
  scripts/
    download_data.py           # Fetches Rebrickable CSVs + LDConfig.ldr
  pyproject.toml
  master_plan.md
  CLAUDE.md
  .env.example
  .gitignore
```

## 8. Key Design Decisions

**REST API over server-side rendering.** Brickomancer is designed as a clean REST API from day one. The React frontend is a replaceable layer — swapping it for React Native (phone) or Electron (desktop) in a future version requires no changes to the Python backend. All generation logic stays server-side.

**Ephemeral sessions, no database.** Per-request temp directories replace persistent storage. For a personal single-user tool, this eliminates auth, migration, and backup concerns entirely. Adding SQLite later (for job history, saved builds) requires only adding a data-service layer.

**LDraw + LPub3D for instruction generation.** LPub3D headless produces publication-quality instruction pages (step numbers, PLI icons, callout boxes) that would take weeks to replicate with ReportLab. Confirmed headless CLI mode (`lpub3d -pdf -o <dir> <ldr>`). GPL v3 is acceptable for personal local use; review subprocess-isolation exemption before any public deployment.

**CLAUDE_CODE_OAUTH_TOKEN subprocess for piece detection.** Matches void_furnace's proven auth pattern — no API key billing on top of the existing subscription. The piece detector is abstracted behind `subprocess_utils.run_claude_subprocess()`; swapping to a local vision model (LLaVA via llama.cpp) requires changing one function.

**TripoSR for image-to-3D.** Generates a closed watertight mesh from a single photo (including back geometry). Monocular depth estimation only gives a 2.5D front-surface shell — inadequate for solid voxelization. MIT license. Requires CUDA GPU (6 GB+ VRAM); confirmed available per void_furnace substrate (runs 30B+ GGUF models with llama.cpp CUDA).

**Greedy packing with masonry offset over ILP.** Tractable in milliseconds for models up to ~5000 bricks. The masonry offset heuristic (alternating scan start by 1 stud on odd layers) prevents vertical fault planes without a constraint solver. OR-Tools CP-SAT per-layer ILP is the V2 upgrade path for structural quality.

**Llama 3.2-1B via llama-server for text→shape.** Keeps all generative inference local with zero API cost. HTTP calls against llama-server match void_furnace's `llamacpp` adapter pattern exactly. The model only extracts shape parameters (archetype, dimensions, colors) — it does NOT run the full LegoGPT brick-generation loop, so the 20×20×20 grid constraint does not apply.

**Synchronous FastAPI endpoints + React spinner.** Single-user personal tool; request latency is acceptable (TripoSR ~2s, LDView ~1s × 3, LPub3D ~30s). No job queue needed for V1. Upgrade to `asyncio.run_in_executor` or a task queue if response times become problematic.

## 9. Open Questions / Risks

| Item | Risk | Mitigation |
|---|---|---|
| TripoSR quality for organic shapes | Animals, irregular objects may produce poor geometry | Manual height_studs confirmation by user; shape parameterization fallback |
| LPub3D headless on Windows | Some versions have bugs with the `-o` flag for PNG output | Test early in Step 9; fallback: LDView per-step PNGs + ReportLab PDF assembly |
| llama-server availability | Assumes llama-server already running on port 8080 | Startup health check in `main.py`; `/api/status` exposes `llama_server_ok` |
| Claude subprocess output parsing | Claude output format may vary between invocations | Enforce JSON via system prompt; retry up to 2× with parse validation |
| Scale calibration | TripoSR mesh is unitless; real-world size unknown | User confirms `height_studs` in UI after mesh is generated; default 10 studs |
| Rebrickable CDN availability | CSVs may be unavailable at download_data.py time | Bundle a minimal 30-color fallback palette in the repo |
| LDView path on Windows | LDView binary name may differ on Windows | Document both `LDView` (Linux) and `ldview.exe` (Windows); detect at startup |
| brickalize package interlocking | PyPI `brickalize` does not enforce interlocking | Build custom packer from scratch in Step 6; reference brickalize for voxel API only |

## 10. How to Run

**Prerequisites:**
- Python 3.12+, uv, Node.js 20+
- CUDA GPU with 6 GB+ VRAM (for TripoSR)
- llama-server running with Llama 3.2-1B GGUF on port 8080 (void_furnace llama.cpp setup)
- LDView installed and on PATH (`LDView --version` or `ldview --version` works)
- LPub3D installed and on PATH (`lpub3d -?` works)
- `CLAUDE_CODE_OAUTH_TOKEN` set in `.env`

**Setup:**
```powershell
cd C:\Users\abero\dev\brickomancer
uv sync
cd frontend; npm install; cd ..
uv run python scripts/download_data.py
```

**Run:**
```powershell
# Terminal 1 — backend
uv run fastapi dev src/brickomancer/main.py     # → http://localhost:8000

# Terminal 2 — frontend
cd frontend; npm run dev                         # → http://localhost:5173
```

**Test:**
```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

**Health check:**
```powershell
curl http://localhost:8000/api/status
```

## 11. Development Process

Build via `/build-phase --plan master_plan.md`. All automated steps use `--reviewers code` (backend/library work throughout) and default `--isolation worktree`.

### Automated Steps

### Step 1: Project scaffold
- **Problem:** Create FastAPI backend shell (`main.py`, `routers/`, `services/`, `models/`, `utils/`), React + Vite frontend shell, `uv` `pyproject.toml` with all Python deps, CORS wiring, `.env.example`, `.gitignore`, empty `tmp/` and `data/` directories, base pytest config, Vite config with `server.port=5173 strictPort=true proxy={/api: localhost:8000}`
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `pyproject.toml`, `src/brickomancer/main.py`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/App.tsx`, `.env.example`, `.gitignore`
- **Done when:** `uv run fastapi dev src/brickomancer/main.py` starts and `GET /api/status` returns HTTP 200; `npm run dev` in `frontend/` starts and serves index page; `uv run pytest -q` exits 0; `uv run mypy src` exits 0
- **Depends on:** none

### Step 2: Data layer
- **Problem:** `scripts/download_data.py` downloads Rebrickable CC0 CSVs and `LDConfig.ldr` to `data/`. `data_service.py` parses and loads color palette + parts catalog at FastAPI startup. Expose `get_color(id)`, `get_part(num)`, `list_colors()`. Parse LDConfig.ldr `!COLOUR` entries for the authoritative `CODE → VALUE (#hex)` mapping.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `scripts/download_data.py`, `src/brickomancer/services/data_service.py`, `tests/test_data_service.py`
- **Done when:** `uv run python scripts/download_data.py` completes and all 5 files appear in `data/`; `data_service.list_colors()` returns ≥100 entries each with non-empty hex; `get_color(15)` returns White with hex `F4F4F4`; unit tests pass
- **Depends on:** Step 1

### Step 3: Color mapping module
- **Problem:** `color_service.py` implements (1) KMeans k=8 in Lab color space for dominant color extraction from images, (2) ΔE2000 nearest-LEGO-color matching using `basic-colormath`. Add `scikit-learn`, `scikit-image`, `Pillow`, `basic-colormath` to `pyproject.toml`.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/color_service.py`, `tests/test_color_service.py`
- **Done when:** `extract_colors("tests/integration/fixtures/cake.jpg")` returns dominant colors that include matches to White, Yellow, and a blue variant (Light Bluish Gray or similar); `match_color("F4F4F4")` → White (id=15); unit tests pass including Lab-space conversion
- **Depends on:** Step 2

### Step 4: Image → 3D pipeline
- **Problem:** `image_pipeline.py` implements: (1) `rembg` background removal → transparent PNG, (2) TripoSR inference → watertight OBJ, (3) trimesh mesh loading + scale to `height_studs * 0.0096m`, (4) `mesh.voxelized(pitch=8.0, method='ray').fill()` → numpy bool array. Add `rembg`, `trimesh`, `torchmesh`, and TripoSR to deps.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/image_pipeline.py`, `tests/test_image_pipeline.py`
- **Done when:** `image_pipeline.run("tests/integration/fixtures/cake.jpg", height_studs=8)` returns numpy bool array with shape `(X, 8, Z)` where X,Z > 2; no CUDA OOM; unit test with small fixture image passes
- **Depends on:** Step 1

### Step 5: Text → shape pipeline
- **Problem:** `text_pipeline.py` sends a description string to llama-server at `localhost:8080` (llama.cpp, OpenAI-compatible `/v1/chat/completions`), extracts structured shape params (see Appendix §12.3 for prompt), builds a trimesh primitive from the archetype, voxelizes it. Raises `ServiceUnavailableError` when llama-server is unreachable.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/text_pipeline.py`, `tests/test_text_pipeline.py`
- **Done when:** `text_pipeline.run("big blue birthday cake")` with real llama-server returns numpy bool array consistent with a cylinder ~8 studs tall; unit tests pass with mocked `httpx` call; `ServiceUnavailableError` raised when server unavailable
- **Depends on:** Step 1

### Step 6: Brick packing + LDraw output
- **Problem:** `brick_packer.py` implements greedy layer-by-layer placement (brick type list: 2×4, 2×3, 2×2, 1×4, 1×3, 1×2, 1×1), masonry offset, interlocking check, and connectivity repair via networkx adjacency graph. `ldraw_writer.py` converts `list[BrickPlacement]` to a valid `.ldr` file with Y-sorted step sequencing (8 bricks/step). Add `networkx` to deps.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/brick_packer.py`, `src/brickomancer/services/ldraw_writer.py`, `src/brickomancer/models/brick.py`, `tests/test_brick_packer.py`, `tests/test_ldraw_writer.py`
- **Done when:** A 5×5×5 bool voxel cube → placement list where every brick at layer y>0 has ≥1 stud connection to layer y-1; the resulting `.ldr` file is accepted by `LDView <file>` without error; `0 STEP` markers appear after every 8 bricks; unit tests pass
- **Depends on:** Step 1

### Step 7: Piece detection from photos
- **Problem:** `piece_detector.py` calls `claude` CLI subprocess via `CLAUDE_CODE_OAUTH_TOKEN` with the prompt in Appendix §12.4. Parses JSON output to `list[PieceCount]`. `merge_piece_lists()` sums quantities for duplicate `(part_id, color)` pairs across multiple photos. `subprocess_utils.run_claude_subprocess()` wraps the subprocess call with 2× retry on JSON parse failure.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/piece_detector.py`, `src/brickomancer/utils/subprocess_utils.py`, `tests/test_piece_detector.py`
- **Done when:** `detect_pieces(["tests/integration/fixtures/lego_cake.jpeg"])` returns ≥1 `PieceCount` with a valid 4-digit `part_id`; unit tests mock the subprocess; `merge_piece_lists()` correctly sums duplicate entries
- **Depends on:** Step 1

### Step 8: Suggestion generation + preview rendering
- **Problem:** `suggestion_service.py` generates 3 suggestions (compact/standard/detailed tiers) from a voxel grid: downsamples for compact tier (every-other-stud), runs `brick_packer.pack()` for each, assigns colors from color palette, writes LDraw files via `ldraw_writer`, calls LDView headless for each preview PNG, extracts parts list from placements. Returns `list[Suggestion]`.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/suggestion_service.py`, `tests/test_suggestion_service.py`
- **Done when:** Given a cylinder voxel grid (8×5×5), `generate_suggestions()` returns exactly 3 `Suggestion` objects; each has a non-empty `preview_url` pointing to an existing PNG; each has a non-empty `parts_list`; the 3 suggestions have different `parts_count` values; unit tests pass with mocked LDView subprocess
- **Depends on:** Steps 3, 6

### Step 9: Instruction PDF generation
- **Problem:** `instruction_service.py` calls LPub3D headless (`lpub3d -pdf -o <dir> <ldr>`) via `subprocess_utils.run_lpub3d()`. Raises `ToolUnavailableError` if LPub3D not on PATH. Returns path to generated PDF.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `src/brickomancer/services/instruction_service.py`, `tests/test_instruction_service.py`
- **Done when:** `generate_pdf(ldr_path, tmp_dir)` with the Step 6 test fixture `.ldr` produces a `.pdf` file > 10 KB; unit tests mock the subprocess call; live integration test with real LPub3D CLI produces a readable PDF; `ToolUnavailableError` raised when LPub3D not on PATH
- **Depends on:** Step 6

### Step 10: React UI — full workflow
- **Problem:** Build the complete 4-step React UI: `WorkflowStepper` (step manager), `InputStep` (image upload or text textarea with toggle), `PiecesStep` (multi-file upload + skip), `SuggestionsStep` (gallery of 3 cards: preview image, tier badge, parts count, "Generate Instructions" button), `InstructionsStep` (spinner during POST, download button on success). Wire `useGenerate` hook to all FastAPI routes. All routes wired end-to-end.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `frontend/src/components/` (all 4 components + WorkflowStepper), `frontend/src/hooks/useGenerate.ts`, `frontend/src/types.ts`, updated `frontend/src/App.tsx`
- **Done when:** `tsc --noEmit` exits 0; `npm run build` succeeds; all 5 FastAPI routes return correct shapes from `curl`
- **Depends on:** Steps 1, 8, 9

### Step 11: Integration smoke gate
- **Problem:** `tests/integration/test_smoke.py` exercises the full pipeline end-to-end with real services (no mocks): POST `cake.jpg` to `/api/generate/from-image`, assert 3 suggestions returned, assert each has a `preview_url` resolving to a non-empty PNG on disk, assert `parts_list` non-empty. Also POST `"big blue birthday cake"` to `/api/generate/from-text` and assert same structure. Add `cake.jpg` and `lego_cake.jpeg` to `tests/integration/fixtures/`.
- **Issue:** #
- **Flags:** --reviewers code
- **Produces:** `tests/integration/test_smoke.py`, `tests/integration/fixtures/cake.jpg`, `tests/integration/fixtures/lego_cake.jpeg`
- **Done when:** `uv run pytest tests/integration/ -v` passes with all real services running; full image pipeline completes in < 120s; no exceptions in FastAPI server logs
- **Depends on:** Steps 4, 5, 6, 7, 8, 9, 10

### Manual Steps

### Step M1: End-to-end UAT
- **Source step:** Step 11 (smoke gate must pass first)
- **Issue:** #
- **Commands:**
  ```powershell
  # Terminal 1
  uv run fastapi dev src/brickomancer/main.py

  # Terminal 2
  cd frontend; npm run dev

  # Open http://localhost:5173 in browser
  ```
- **What to look for:**

  | Check | Expected outcome |
  |---|---|
  | Upload `cake.jpg`, set height=8 studs, click Generate | Spinner shown; 3 suggestion cards appear with preview images |
  | Suggestion previews | Each shows a distinct LEGO model; visibly different sizes/complexity across tiers |
  | Parts list on each card | Non-empty; includes recognizable brick type names (2×4 brick, 1×2 brick, etc.) |
  | Upload `lego_cake.jpeg` as piece photo | Detected parts appear before suggestions; non-empty part list shown |
  | Click "Generate Instructions" on Standard suggestion | Spinner while LPub3D runs; PDF downloads automatically |
  | Open downloaded PDF | Multi-page document; step numbers visible; brick additions shown per step |
  | Text input: "big blue birthday cake" | Generates suggestions with blue-dominant color palette; cylinder-like shapes |
  | `/api/status` endpoint | `{llama_server_ok: true, ldview_ok: true, lpub3d_ok: true}` |

After M1 passes, Brickomancer V1 is complete.

## 12. Appendix

### 12.1 LDraw Coordinate System

| LEGO unit | LDraw Units (LDU) | mm |
|---|---|---|
| 1 stud pitch (XZ) | 20 LDU | 8 mm |
| 1 brick height (Y) | 24 LDU | 9.6 mm |
| 1 plate height (Y) | 8 LDU | 3.2 mm |

LDraw Y-axis is inverted: Y increases downward in LDraw space. Ground layer (packer y=0) maps to `y_ldu = 0`. Layer y=1 maps to `y_ldu = -24`.

Common part IDs used by the packer:

| Brick | Part ID | LDU footprint (X × Z) |
|---|---|---|
| 1×1 brick | 3005 | 20 × 20 |
| 1×2 brick | 3004 | 20 × 40 |
| 1×3 brick | 3622 | 20 × 60 |
| 1×4 brick | 3010 | 20 × 80 |
| 2×2 brick | 3003 | 40 × 40 |
| 2×3 brick | 3002 | 40 × 60 |
| 2×4 brick | 3001 | 40 × 80 |

### 12.2 Rebrickable colors.csv Schema (CC0)

```
id,name,rgb,is_trans,num_parts,num_sets,y1,y2
15,White,F4F4F4,False,3842,18741,1950,2024
0,Black,212121,False,3201,17943,1950,2024
4,Red,B40000,False,1893,12905,1950,2024
1,Blue,1E5AA8,False,1765,11820,1950,2024
...
```

Load with `pandas.read_csv("data/rebrickable/colors.csv")`. Filter `is_trans == False` for V1 solid palette (~78 active colors).

### 12.3 LDConfig.ldr Color Entry Format

```
0 !COLOUR White   CODE 15  VALUE #F4F4F4  EDGE #9C9291
0 !COLOUR Black   CODE 0   VALUE #1B2A34  EDGE #255255255
0 !COLOUR Red     CODE 4   VALUE #B40000  EDGE #7D0000
```

Parse: split on whitespace, extract `CODE` → int (LDraw color ID), `VALUE` → `#RRGGBB` hex string.

### 12.4 Claude Piece Detection Prompt

```
You are a LEGO piece identifier. Identify all visible LEGO pieces in this image.
Return ONLY valid JSON as a list — no other text:
[{"part_id": "<4-or-5-digit-lego-part-number>", "qty": <integer>, "color": "<lego_color_name>"}, ...]
If you cannot identify a piece with confidence, omit it entirely.
Common part IDs: 3001 (2×4 brick), 3003 (2×2 brick), 3004 (1×2 brick), 3005 (1×1 brick),
3010 (1×4 brick), 60474 (4×4 round plate), 11213 (6×6 round plate).
```

### 12.5 Llama Shape Extraction Prompt

```
Extract LEGO build shape parameters from the following description.
Return ONLY valid JSON — no other text:
{
  "archetype": "<one of: cylinder, box, sphere, cone, house, compound>",
  "height_studs": <integer 2-20>,
  "radius_studs": <integer 2-15, for cylinder/sphere/cone>,
  "width_studs": <integer 2-20, for box/house/compound>,
  "depth_studs": <integer 2-20, for box/house/compound>,
  "colors": ["<lego_color_name>", ...]
}
Omit fields that do not apply to the archetype.

Description: {description}
```

### 12.6 Safe V1 Color Palette (28 colors)

The 28 LEGO colors reliably available in standard brick sizes via Pick-a-Brick and major sets (from INV-6 research). Brickomancer's V1 color matcher restricts suggestions to this set.

| Name | Rebrickable ID | Hex |
|---|---|---|
| Black | 0 | 1B2A34 |
| White | 15 | F4F4F4 |
| Light Bluish Gray | 71 | 969696 |
| Dark Bluish Gray | 72 | 646464 |
| Red | 4 | B40000 |
| Blue | 1 | 1E5AA8 |
| Yellow | 14 | FAC80A |
| Green | 2 | 00852B |
| Orange | 25 | D67923 |
| Dark Red | 320 | 6D0001 |
| Dark Blue | 272 | 0A3463 |
| Dark Green | 288 | 184632 |
| Lime | 27 | A5CA18 |
| Bright Green | 10 | 58AB41 |
| Tan | 19 | B0A06F |
| Dark Tan | 28 | 897D62 |
| Reddish Brown | 70 | 5F3109 |
| Brown | 6 | 543324 |
| Medium Blue | 73 | 7396C8 |
| Sand Green | 151 | 7D9C8B |
| Olive Green | 330 | 9B9A5A |
| Medium Azure | 322 | 36AEBF |
| Bright Light Blue | 212 | 9DC3F7 |
| Bright Light Orange | 191 | FCAC00 |
| Bright Light Yellow | 226 | FFEC6C |
| Lavender | 31 | CDA4DE |
| Medium Lavender | 30 | A06EB9 |
| Nougat | 18 | BB805A |

# Brickomancer — Project Instructions

## Project overview

LEGO build generator. Takes a photo of a real-world object (or a text description) and produces 3 build suggestions (compact/standard/detailed) with rendered previews and parts lists, then generates a downloadable step-by-step instruction book (official LEGO style) for the selected suggestion. Optionally identifies available LEGO pieces from photos (via Claude OAuth subprocess) and uses them as soft build constraints. Local-first personal tool; REST API designed for future migration to a phone or desktop frontend.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → 3D → voxels | rembg (background removal) + Hunyuan3D-2mini (CUDA GPU) + trimesh voxelization |
| Text → shape | Llama 3.2-1B via llama-server (llama.cpp, port 8080) |
| Piece detection | Claude claude-sonnet-4-6 via `CLAUDE_CODE_OAUTH_TOKEN` subprocess |
| Color matching | scikit-learn + scikit-image + basic-colormath |
| Parts data | Rebrickable CC0 CSVs + LDraw LDConfig.ldr (offline, in `data/`) |
| 3D rendering | LDView (headless CLI, must be on PATH) |
| Instruction PDF | LPub3D (headless CLI, must be on PATH) |
| Testing | pytest, ruff, mypy |

## Key commands

```powershell
uv sync                                           # Install Python deps
cd frontend; npm install; cd ..                   # Install JS deps
uv run python scripts/download_data.py            # Fetch Rebrickable CSVs + LDConfig.ldr

# Run (Windows — fastapi dev fails on cp1252 terminals due to emoji; use uvicorn directly)
$env:PATH += ";C:\Tools\LPub3D"                              # Must be set before starting server
uv run uvicorn --app-dir src brickomancer.main:app           # Backend → http://localhost:8000 (no --reload)
cd frontend; npm run dev                                     # Frontend → http://localhost:5173

# Quality gates
uv run pytest -q
uv run ruff check .
uv run mypy src
npm run build --prefix frontend
```

## Directory layout

```
brickomancer/
  src/brickomancer/
    main.py                   # FastAPI app, CORS, startup data load
    routers/                  # generate.py, info.py
    services/                 # color_service, data_service, shaper (seam),
                              # image_shaper, brick_packer, ldraw_writer,
                              # piece_detector, suggestion_service, instruction_service
                              # (text_shaper lands in Step 6)
    models/                   # schemas.py (Pydantic), brick.py (dataclasses + BRICK_PART_IDS, TILE_PART_IDS)
    utils/                    # temp_dir.py, subprocess_utils.py
  frontend/src/
    components/               # WorkflowStepper, InputStep, PiecesStep,
                              # SuggestionsStep, InstructionsStep
    hooks/useGenerate.ts
    types.ts
  data/rebrickable/           # CC0 CSVs (gitignored; run download_data.py)
  data/ldraw/                 # LDConfig.ldr + dimensions.csv
  tmp/                        # Per-request scratch (gitignored)
  tests/                      # Unit tests + integration/test_smoke.py
                              # tests/harness/ REMOVED in Phase 1 — rebuilt fresh in Step 9
  scripts/download_data.py
  .claude/skills/run-harness/ # /run-harness skill — STALE until Step 9 rebuilds the harness
```

## Architecture summary

**Backend (FastAPI):** Stateless REST API. Each request allocates a `tmp/<uuid>/` scratch directory (persists in V1 — no cleanup; LDR files must survive the `/instructions` call that follows). Two input paths, both behind the `Shaper` seam (`to_voxels() -> (X, Y, Z)` bool grid): image (`ImageShaper`: rembg background removal → Hunyuan3D-2mini → `trimesh.voxelized(method="subdivide").fill()` → crop/clamp/pad → voxel grid) or text (`TextShaper`, Step 6 — not yet built; `/from-text` still 503). Both converge at the connectivity-graph brick packer → LDraw file → LDView PNG previews. LPub3D generates the final instruction PDF from the selected suggestion's LDraw file.

**Frontend (React):** 4-step wizard. POSTs to FastAPI and shows a spinner during synchronous requests. No job queue needed for V1.

**External services (must be running/on PATH before starting backend):**
- `llama-server` on port 8080 with Llama 3.2-1B GGUF (void_furnace llama.cpp setup)
- `LDView` auto-detected at `C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe` (no PATH needed)
- `LPub3D.exe` on PATH (install at `C:\Tools\LPub3D\`; add to `$env:PATH` before starting server)
- `CLAUDE_CODE_OAUTH_TOKEN` as Windows user env var (for piece detection subprocess; never ANTHROPIC_API_KEY)
- Start server WITHOUT `--reload` — WatchFiles subprocess does not inherit session PATH

## Current state

**FULL REBUILD in progress** (decided 2026-06-16; v1 plateaued at ~5/10 for architectural reasons —
the silhouette+dome image path fabricated depth, and the pytest-only harness gate never re-rendered).
Plan: [`documentation/rebuild-plan.md`](documentation/rebuild-plan.md). Investigation +
distillation: [`docs/investigations/rebuild/`](docs/investigations/rebuild/). GitHub umbrella #46,
step issues #47-#59 (namespaced "Rebuild —"). The old v1 harness was REMOVED in Phase 1 (rebuilt
fresh in Step 9; reference artifacts archived to `docs/rebuild_reference/`).

**Progress: Phase 0 + Phase 1 + Phase 2 Steps 3 & 4 + Phase 3 Step 5 DONE.** 253 tests passing,
0 type errors, 0 lint violations.
- **Phase 0:** Hunyuan3D-2mini chosen for image→3D (TripoSG install-blocked on Windows). **Toolchain
  finding: `INSERT COVER_PAGE` crashes LPub3D 2.4.9 → the frozen instruction header is BOM-only**
  (no cover page; render-verified).
- **Phase 1:** in-place clean — `image_pipeline.py`/`text_pipeline.py` + old harness removed; the
  `Shaper` seam (`services/shaper.py`, `to_voxels() -> (X,Y,Z) bool grid`) is the swap point everything
  downstream builds against; grid-dim constants live in `models/brick.py`. (`/from-image` is now wired
  to `ImageShaper` — Step 5 below; `/from-text` stays 503 until Step 6; `/instructions` + `/api/status`
  unchanged.)
- **Phase 2 Step 3:** connectivity-graph packer (`build_connectivity_graph`,
  `connected_component_count`, `unsupported_bricks`, `articulation_points`).
  cube/star → 1 connected component + 0 unsupported; masonry seams preserved.
- **Phase 2 Step 4 (#53):** **in-volume bonding replaces the cap-above merge → ZERO added height**
  for the cube, plus-star, and all masonry grids (was cube +1 / star +4). New bond-only `(2,1)` part
  (LDraw 3004 rotated 90° about Y; matrix `0 0 1 0 1 0 -1 0 0` — **render-verified** via
  `scripts/step4_render_uat.py`, the (2,1) renders ⊥ to the (1,2)). The bonder
  (`_bond_components_in_volume`) is a spanning-tree solver: z-clean → z-extend (grow a `(1,N)` span to
  absorb a z-fragment) → x-clean → z/x-decompose, each guarded (strict-merge, no float, no added
  height; x-bonds seam-gated). A degree-4 hub (plus-star centre) is solved by z-extend reusing a
  layer. Phase C (`_eliminate_arm_tip_articulations`, z-only) hardens single-bond fragments into
  cycles. Tile pass is now **1-for-1 only** (splitting a wide top brick severed bonds — adversarial
  review BLOCKER). Known limitation: minimum-depth slabs (Z=2) and Y=2,Z∈{5,9} keep +1/+2 height via
  the cap fallback (still 1 component, 0 unsupported); all thick grids (Y≥3 ∧ Z≥3) are zero-height.
- **Phase 3 Step 5 (#54):** `ImageShaper` (`services/image_shaper.py`) behind the `Shaper` seam:
  rembg → Hunyuan3D-2mini → `trimesh.voxelized(method="subdivide").fill()` → `_fit_to_bounds`
  (crop to occupied bbox, center-crop oversized axes, edge-pad sub-2 axes) → `validate_grid`. Wired
  through `/api/generate/from-image` (save upload → shape → `color_service` → optional piece detect →
  `suggestion_service`). `ModelUnavailableError` (no torch/CUDA/`hy3dgen`/weights/degenerate mesh) →
  clean 503. **`height_studs` is the resolution knob** (`ImageShaper(max_dim=height_studs)`, clamped
  to `[2, 32]`): the spike's `max_dim=28` packs ~66 s/tier (×3 = unusable); `max_dim≈10` packs <2 s.
  Integration test runs the model **mocked** through the router + a 503 test. **DEFERRED to an
  operator Test:** the plan's literal done-when (live star-survival, top-down ≥4 protrusions on the
  real model) — Hunyuan3D isn't in the project venv yet (see Environment requirements).

**Next action: Phase 3 Step 6 (#55)** — `TextShaper`: Claude CLI emits a sparse 20³ voxel occupancy
(strict JSON schema) → fill the `(X,Y,Z)` grid behind the same `Shaper` seam, wired through
`/api/generate/from-text` (integration test through the router per code-quality rule). Then Steps 7–8
+ Phase 4 (Steps 9–10, the rebuilt harness). **Also pending:** the Step 5 live star-survival operator
Test once Hunyuan3D-2mini is installed in the project venv.

**`CLAUDE_CODE_OAUTH_TOKEN` note:** Set as a Windows user environment variable (not `.env`). Load in
PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`.
The Bash tool does NOT inherit Windows user env vars.

**pytest note:** clean gate is `uv run pytest -q --ignore=tests/integration`. Integration gate:
`BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/ -v`.

## Environment requirements

- Windows 11, Python 3.12+, uv, Node.js 20+
- llama-server running before backend start (port 8080) — text path only (Step 6, not yet built)
- **Image path now requires a CUDA GPU + Hunyuan3D-2mini installed in the project venv** (rembg → Hunyuan3D → voxelize); `/api/generate/from-image` returns a clean 503 if torch/CUDA/`hy3dgen`/weights are unavailable. The model is currently installed only in the throwaway spike venv (`C:\Tools\spike3d`); the project venv has `torch+cu118`/`rembg`/`trimesh` but not `hy3dgen` + the 7.64 GB weights yet
- LDView auto-detected at `C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe` (no PATH needed)
- LPub3D on PATH (`$env:PATH += ";C:\Tools\LPub3D"`) before starting server
- `CLAUDE_CODE_OAUTH_TOKEN` as Windows user environment variable (not `.env`; inherited by `.bat` launcher; load manually in PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`)
- `PYTHONIOENCODING=utf-8` recommended (workspace Unicode print rule)

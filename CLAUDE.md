# Brickomancer — Project Instructions

## Project overview

LEGO build generator. Takes a photo of a real-world object (or a text description) and produces 3 build suggestions (compact/standard/detailed) with rendered previews and parts lists, then generates a downloadable step-by-step instruction book (official LEGO style) for the selected suggestion. Optionally identifies available LEGO pieces from photos (via Claude OAuth subprocess) and uses them as soft build constraints. Local-first personal tool; REST API designed for future migration to a phone or desktop frontend.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → voxels | rembg (background removal) + 2D silhouette extrusion |
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
    services/                 # color_service, data_service, image_pipeline,
                              # text_pipeline, brick_packer, ldraw_writer,
                              # piece_detector, suggestion_service, instruction_service
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
                              # tests/harness/ — run_harness.py, advisors.yaml, scores.jsonl, runs/
  scripts/download_data.py
  .claude/skills/run-harness/ # /run-harness skill (prep + launch + monitor)
```

## Architecture summary

**Backend (FastAPI):** Stateless REST API. Each request allocates a `tmp/<uuid>/` scratch directory (persists in V1 — no cleanup; LDR files must survive the `/instructions` call that follows). Two input paths: image (rembg background removal → 2D silhouette extrusion → voxel grid) or text (Llama 3.2-1B → primitive mesh → trimesh voxelization). Both converge at brick packing → LDraw file → LDView PNG previews. LPub3D generates the final instruction PDF from the selected suggestion's LDraw file.

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

**Progress: Phase 0 + Phase 1 + Phase 2 Steps 3 & 4 DONE.** 240 tests passing,
0 type errors, 0 lint violations.
- **Phase 0:** Hunyuan3D-2mini chosen for image→3D (TripoSG install-blocked on Windows). **Toolchain
  finding: `INSERT COVER_PAGE` crashes LPub3D 2.4.9 → the frozen instruction header is BOM-only**
  (no cover page; render-verified).
- **Phase 1:** in-place clean — `image_pipeline.py`/`text_pipeline.py` + old harness removed; the
  `/api/generate/from-image` and `from-text` routes are **503-stubbed** until the Shapers land
  (Steps 5/6); `/api/generate/instructions` + `/api/status` unchanged. The `Shaper` seam
  (`services/shaper.py`, `to_voxels() -> (X,Y,Z) bool grid`) is the swap point everything downstream
  builds against; grid-dim constants live in `models/brick.py`.
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

**Next action: Phase 3 Step 5 (#54)** — `ImageShaper` (rembg → Hunyuan3D-2mini → voxelize → `(X,Y,Z)`
grid) behind the `Shaper` seam, wired through the `/api/generate/from-image` route (integration test
required per code-quality rule). The packer now consumes whatever grid the Shaper emits.

**`CLAUDE_CODE_OAUTH_TOKEN` note:** Set as a Windows user environment variable (not `.env`). Load in
PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`.
The Bash tool does NOT inherit Windows user env vars.

**pytest note:** clean gate is `uv run pytest -q --ignore=tests/integration`. Integration gate:
`BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/ -v`.

## Environment requirements

- Windows 11, Python 3.12+, uv, Node.js 20+
- llama-server running before backend start (port 8080) — text pipeline only; image pipeline (2D silhouette extrusion) works without it and without a GPU
- LDView auto-detected at `C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe` (no PATH needed)
- LPub3D on PATH (`$env:PATH += ";C:\Tools\LPub3D"`) before starting server
- `CLAUDE_CODE_OAUTH_TOKEN` as Windows user environment variable (not `.env`; inherited by `.bat` launcher; load manually in PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`)
- `PYTHONIOENCODING=utf-8` recommended (workspace Unicode print rule)

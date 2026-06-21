# Brickomancer

Takes a photo of a real-world object (or a text description) and produces 3 LEGO build suggestions — compact, standard, and detailed — each with a rendered 3D preview and a parts list. Select one and download a step-by-step instruction book in official LEGO manual style.

Optionally photograph your own LEGO piece pile: Brickomancer identifies available parts and uses them as soft build constraints.

Local-first personal tool. Python/FastAPI backend + React frontend. Clean REST API designed for future migration to a phone or desktop app.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → 3D → voxels | rembg (background removal) + Hunyuan3D-2mini (CUDA GPU) + trimesh voxelization |
| Voxelization | trimesh (`voxelized(method="subdivide").fill()`) |
| Text → shape | Claude CLI (`claude -p`) sparse-voxel emit via `CLAUDE_CODE_OAUTH_TOKEN` |
| Piece detection | Claude claude-sonnet-4-6 via `CLAUDE_CODE_OAUTH_TOKEN` subprocess |
| Color matching | scikit-learn + scikit-image + basic-colormath (ΔE2000) |
| Parts database | Rebrickable CC0 CSVs + LDraw LDConfig.ldr (offline) |
| 3D rendering | LDView (headless CLI) |
| Instruction PDF | LPub3D (headless CLI) |
| Testing | pytest, ruff, mypy |

## Prerequisites

- Python 3.12+, uv, Node.js 20+
- `claude` CLI on PATH with `CLAUDE_CODE_OAUTH_TOKEN` set (text path — `claude -p` sparse-voxel emit; no GPU, no llama-server)
- `LDView` on PATH (`LDView --version` or `ldview --version` works)
- `LPub3D` on PATH (`lpub3d -?` works)
- **Image path:** a CUDA GPU + Hunyuan3D-2mini installed in the project venv. `POST /api/generate/from-image` returns a clean 503 if torch/CUDA/`hy3dgen`/weights are unavailable. (Currently installed only in the throwaway spike venv `C:\Tools\spike3d`.)
- `CLAUDE_CODE_OAUTH_TOKEN` set as a **Windows user environment variable** (not `.env`); load in PowerShell via `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`

## Setup

```powershell
uv sync
cd frontend; npm install; cd ..
uv run python scripts/download_data.py   # downloads ~50 MB of Rebrickable CSVs + LDConfig.ldr
```

## Run

```powershell
# Terminal 1 — backend (fastapi dev fails on cp1252 Windows terminals; use uvicorn)
$env:PATH += ";C:\Tools\LPub3D"                              # before starting the server
uv run uvicorn --app-dir src brickomancer.main:app           # http://localhost:8000 (no --reload)

# Terminal 2 — frontend
cd frontend; npm run dev                         # http://localhost:5173
```

Health check:

```powershell
curl http://localhost:8000/api/status
# {"status":"ok","llama_server_ok":true,"ldview_ok":true,"lpub3d_ok":true}
```

## Test

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
npm run build --prefix frontend
```

## Pipeline

```
Photo/text input
  ↓
Image path: rembg (background removal) → Hunyuan3D-2mini → trimesh voxelization → (X,Y,Z) voxel grid (ImageShaper)
Text path:  TextShaper → claude -p sparse 20³ voxel occupancy → fill/crop → (X,Y,Z) voxel grid
  ↓
Connectivity-graph brick packing (components + grounding + zero-added-height in-volume bonding)
  ↓
3 LDraw files (compact / standard / detailed)
  ↓
LDView renders 3 PNG previews
  ↓
User selects suggestion → LPub3D generates instruction PDF
```

## Key design decisions

- **Ephemeral sessions, no database.** All state lives in a per-request `tmp/<uuid>/` directory. V1 keeps it (no cleanup) so the LDraw file survives the follow-up `/instructions` call; adding job history later requires only a data-service layer.
- **LDraw + LPub3D for instructions.** LPub3D headless produces publication-quality step illustrations; replicating this with ReportLab would take weeks.
- **CLAUDE_CODE_OAUTH_TOKEN subprocess for piece detection.** No API key billing on the existing subscription. The detector is behind `subprocess_utils.run_claude_subprocess()`; swapping to a local LLaVA model requires changing one function.
- **Connectivity-graph packing.** Replaces v1's greedy + masonry + bolt-on-repair: a connectivity graph makes structural weakness (disconnected components, articulation points) visible, and in-volume bonding adds interlocks with zero added height. (Phase 2, Steps 3–4.)
- **Hunyuan3D-2mini for true image→3D.** The v1 2D silhouette+dome heuristic fabricated depth (a star became a domed slab, losing its points); the rebuild voxelizes a real single-image→3D mesh behind the `Shaper` seam. TripoSG was install-blocked on Windows, so Hunyuan3D-2mini (shape-only, no CUDA texture extensions) was chosen in Phase 0.

## Project structure

```
src/brickomancer/
  main.py               FastAPI app, CORS, startup data load
  routers/              generate.py, info.py
  services/             color_service, data_service, shaper (seam),
                        image_shaper, text_shaper, brick_packer, ldraw_writer,
                        piece_detector, suggestion_service, instruction_service
  models/               schemas.py (Pydantic), brick.py (dataclasses)
  utils/                temp_dir.py, subprocess_utils.py
frontend/src/
  components/           WorkflowStepper, InputStep, PiecesStep,
                        SuggestionsStep, InstructionsStep
  hooks/                useGenerate.ts
  types.ts
data/
  rebrickable/          CC0 CSVs (gitignored; run download_data.py)
  ldraw/                LDConfig.ldr + dimensions.csv
tests/
  integration/          test_smoke.py + fixtures/
scripts/
  download_data.py
```

## Status

**Full rebuild in progress — Phase 3 Steps 5 & 6 done, 267 tests passing.** The v1 silhouette+dome image path (which fabricated depth) and the pytest-only quality harness were removed; the project is being rebuilt around a `Shaper` seam (`services/shaper.py`, `to_voxels() -> (X, Y, Z)` bool grid) feeding a connectivity-graph brick packer. Done so far:

- **Phase 0** — Hunyuan3D-2mini chosen for image→3D (TripoSG install-blocked on Windows); the LPub3D instruction header is BOM-only because `INSERT COVER_PAGE` crashes LPub3D 2.4.9.
- **Phase 1** — in-place clean + the `Shaper` seam; the image/text generate routes were 503-stubbed pending the Shapers.
- **Phase 2 Steps 3–4** — connectivity-graph packer (component/unsupported/articulation analysis) + zero-added-height in-volume bonding.
- **Phase 3 Step 5** — `ImageShaper`: rembg → Hunyuan3D-2mini → trimesh voxelize, wired through `POST /api/generate/from-image`; returns 503 when the model/GPU/weights are unavailable. `height_studs` is the resolution knob.
- **Phase 3 Step 6** — `TextShaper`: a `claude -p` subprocess emits a sparse 20³ voxel occupancy (strict JSON) → fill/crop → grid, wired through `POST /api/generate/from-text`; returns 503 when the Claude CLI is unavailable. Retires the v1 llama-server text path (no GPU needed).

Next: Step 7 (suggestion service + preview/instruction wiring), then Step 8 + the rebuilt re-render+re-score harness (Steps 9–10). 267 tests passing, 0 type errors, 0 lint violations. See [`documentation/rebuild-plan.md`](documentation/rebuild-plan.md).

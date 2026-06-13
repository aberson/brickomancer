# Brickomancer

Takes a photo of a real-world object (or a text description) and produces 3 LEGO build suggestions — compact, standard, and detailed — each with a rendered 3D preview and a parts list. Select one and download a step-by-step instruction book in official LEGO manual style.

Optionally photograph your own LEGO piece pile: Brickomancer identifies available parts and uses them as soft build constraints.

Local-first personal tool. Python/FastAPI backend + React frontend. Clean REST API designed for future migration to a phone or desktop app.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → 3D mesh | TripoSR (MIT, Stability AI) + rembg |
| Voxelization | trimesh |
| Text → shape | Llama 3.2-1B via llama-server (llama.cpp, port 8080) |
| Piece detection | Claude claude-sonnet-4-6 via `CLAUDE_CODE_OAUTH_TOKEN` subprocess |
| Color matching | scikit-learn + scikit-image + basic-colormath (ΔE2000) |
| Parts database | Rebrickable CC0 CSVs + LDraw LDConfig.ldr (offline) |
| 3D rendering | LDView (headless CLI) |
| Instruction PDF | LPub3D (headless CLI) |
| Testing | pytest, ruff, mypy |

## Prerequisites

- Python 3.12+, uv, Node.js 20+
- CUDA GPU with 6 GB+ VRAM (for TripoSR)
- `llama-server` running with Llama 3.2-1B GGUF on port 8080
- `LDView` on PATH (`LDView --version` or `ldview --version` works)
- `LPub3D` on PATH (`lpub3d -?` works)
- `CLAUDE_CODE_OAUTH_TOKEN` set in `.env` (copy from `.env.example`)

## Setup

```powershell
uv sync
cd frontend; npm install; cd ..
uv run python scripts/download_data.py   # downloads ~50 MB of Rebrickable CSVs + LDConfig.ldr
```

## Run

```powershell
# Terminal 1 — backend
uv run fastapi dev src/brickomancer/main.py     # http://localhost:8000

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
Image path: rembg → TripoSR → trimesh voxelization
Text path:  llama-server → primitive mesh → trimesh voxelization
  ↓
Brick packing (greedy + masonry offset + interlocking check)
  ↓
3 LDraw files (compact / standard / detailed)
  ↓
LDView renders 3 PNG previews
  ↓
User selects suggestion → LPub3D generates instruction PDF
```

## Key design decisions

- **Ephemeral sessions, no database.** All state lives in a per-request `tmp/<uuid>/` directory, deleted after the response. Adding job history later requires only a data-service layer.
- **LDraw + LPub3D for instructions.** LPub3D headless produces publication-quality step illustrations; replicating this with ReportLab would take weeks.
- **CLAUDE_CODE_OAUTH_TOKEN subprocess for piece detection.** No API key billing on the existing subscription. The detector is behind `subprocess_utils.run_claude_subprocess()`; swapping to a local LLaVA model requires changing one function.
- **Greedy packing with masonry offset.** Tractable in milliseconds for up to ~5000 bricks. OR-Tools CP-SAT per-layer ILP is the V2 upgrade path.
- **TripoSR over monocular depth.** Generates a closed watertight mesh including back geometry — required for solid voxelization. Monocular depth gives only a 2.5D front-surface shell.

## Project structure

```
src/brickomancer/
  main.py               FastAPI app, CORS, startup data load
  routers/              generate.py, info.py
  services/             color_service, data_service, image_pipeline,
                        text_pipeline, brick_packer, ldraw_writer,
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

**Surface tiles + color_match advisor** — First harness run complete; top-surface bricks tile-smoothed via `_apply_surface_tiles()`; `part_variety` advisor replaced with `color_match` (reads preview + input image). 303 tests passing, 0 type errors, 0 lint violations.

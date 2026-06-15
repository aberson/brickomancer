# Brickomancer

Takes a photo of a real-world object (or a text description) and produces 3 LEGO build suggestions — compact, standard, and detailed — each with a rendered 3D preview and a parts list. Select one and download a step-by-step instruction book in official LEGO manual style.

Optionally photograph your own LEGO piece pile: Brickomancer identifies available parts and uses them as soft build constraints.

Local-first personal tool. Python/FastAPI backend + React frontend. Clean REST API designed for future migration to a phone or desktop app.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → voxels | rembg (background removal) + 2D silhouette extrusion |
| Voxelization | trimesh (text path) |
| Text → shape | Llama 3.2-1B via llama-server (llama.cpp, port 8080) |
| Piece detection | Claude claude-sonnet-4-6 via `CLAUDE_CODE_OAUTH_TOKEN` subprocess |
| Color matching | scikit-learn + scikit-image + basic-colormath (ΔE2000) |
| Parts database | Rebrickable CC0 CSVs + LDraw LDConfig.ldr (offline) |
| 3D rendering | LDView (headless CLI) |
| Instruction PDF | LPub3D (headless CLI) |
| Testing | pytest, ruff, mypy |

## Prerequisites

- Python 3.12+, uv, Node.js 20+
- `llama-server` running with Llama 3.2-1B GGUF on port 8080 (text path only)
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
Image path: rembg (background removal) → 2D silhouette extrusion → voxel grid
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
- **2D silhouette extrusion over TripoSR.** rembg alpha-channel mask → stud-grid resize → vertical extrusion gives the correct subject silhouette shape for cartoon/clip-art inputs. TripoSR reconstructed these as rectangular blobs regardless of subject shape.

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

**Harness runs 8–9 complete** — Run 8 (20 iters) lifted avg raw 3.875→5.125: pdf_completeness 0→5, instruction_clarity 1→5, color_match 7→8. Run 9 identified an oscillation pathology (developer agents undoing prior commits without history awareness); corrected with 4 harness improvements: commit-history injection into developer prompt, LPub3D meta-command reference, parse-error retry, and test-failure retry. Prior runs landed: 2D silhouette extrusion, masonry offset, axis transpose, tile Y fix, subject-color filter, Y-layer step sequencing, trailing `0 STEP`, BOM page, tile decomposition, camera angle. 316 tests passing, 0 type errors, 0 lint violations.

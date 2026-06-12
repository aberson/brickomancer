# Brickomancer — Project Instructions

## Project overview

LEGO build generator. Takes a photo of a real-world object (or a text description) and produces 3 build suggestions (compact/standard/detailed) with rendered previews and parts lists, then generates a downloadable step-by-step instruction book (official LEGO style) for the selected suggestion. Optionally identifies available LEGO pieces from photos (via Claude OAuth subprocess) and uses them as soft build constraints. Local-first personal tool; REST API designed for future migration to a phone or desktop frontend.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → 3D | TripoSR (CUDA GPU), rembg, trimesh |
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
uv run uvicorn --app-dir src brickomancer.main:app --reload  # Backend → http://localhost:8000
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
    models/                   # schemas.py (Pydantic), brick.py (dataclasses)
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
  scripts/download_data.py
```

## Architecture summary

**Backend (FastAPI):** Stateless REST API. Each request allocates a `tmp/<uuid>/` scratch directory (persists in V1 — no cleanup; LDR files must survive the `/instructions` call that follows). Two input paths: image (rembg → TripoSR → trimesh voxelization) or text (Llama 3.2-1B → primitive mesh → voxelization). Both converge at brick packing → LDraw file → LDView PNG previews. LPub3D generates the final instruction PDF from the selected suggestion's LDraw file.

**Frontend (React):** 4-step wizard. POSTs to FastAPI and shows a spinner during synchronous requests. No job queue needed for V1.

**External services (must be running/on PATH before starting backend):**
- `llama-server` on port 8080 with Llama 3.2-1B GGUF (void_furnace llama.cpp setup)
- `LDView` or `ldview.exe` on PATH
- `lpub3d` on PATH
- `CLAUDE_CODE_OAUTH_TOKEN` in `.env` (for piece detection subprocess)

## Current state

Steps 1–11 complete (2026-06-11). Full pipeline implemented: image/text → voxels → brick pack → LDraw → LDView previews → suggestion cards → LPub3D instruction PDF. React 4-step UI wired. 180 unit tests passing, 0 type errors, 0 lint violations. Integration smoke tests in `tests/integration/` (skip when services unavailable). Pending: Step M1 manual UAT (requires TripoSR+rembg[gpu] install, LDView+LPub3D on PATH, llama-server running). Bug fix (2026-06-12): RuntimeError from run_ldview now returns 503 instead of 500.

## Environment requirements

- Windows 11, Python 3.12+, uv, Node.js 20+
- CUDA GPU 6 GB+ VRAM (TripoSR inference; confirmed via void_furnace substrate running 30B+ GGUFs)
- llama-server running before backend start (port 8080)
- LDView installed + on PATH
- LPub3D installed + on PATH
- `CLAUDE_CODE_OAUTH_TOKEN` in `.env` (matches void_furnace auth pattern; not ANTHROPIC_API_KEY)
- `PYTHONIOENCODING=utf-8` recommended (workspace Unicode print rule)

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

Steps 1–11 complete (2026-06-11); Harness Steps 12–18 complete + post-build fixes + nine harness runs (2026-06-13/14/15). **Harness refactored (2026-06-15): judge+applier architecture.** 340 unit tests passing, 0 type errors, 0 lint violations.

**Harness architecture:** `run_harness.py` is a thin entry point. Submodules: `pipeline.py`, `advisor.py`, `server.py`, `judge.py`, `applier.py`. Loop: pipeline → 9 advisors (including `warnings_judge`) → quality gate → `judge` (produces structured change brief) → `apply` (Claude subprocess, pytest gate, commit or revert). `developer.py` deleted.

**Judge output schema:** `{dimension, file_path, rationale, approach_description, functions_to_modify, constraints_to_preserve, anti_patterns_to_avoid, blocking_issues, confidence}`. `blocking_issues` non-empty → applier logs SKIPPED_BLOCKED and skips iteration.

**`warnings_judge` (9th advisor):** reads `scores_history` (last 15 rows); detects oscillation, revert storms, regression, stagnation; score 10=healthy, 0=crisis.

**Committed improvements to date (cumulative):**
- 8bd95b3: axis transpose (star face → XZ plane)
- 81fd8e2: tile Y-coordinate fix (tiles flush on studs)
- bd1b576: subject-color filter (yellow star over white background)
- ea0f2d0: masonry offset on odd brick layers (build stability)
- 96ffeb8: replaced TripoSR with 2D silhouette extrusion
- 6d67628: Y-layer-first step sequencing in ldraw_writer
- acf8ca6: trailing `0 STEP` after every step including the last
- (shape-quality plan): sparse-fill guard, 2×2 OR-pool, integration test, axis-convention guard
- d4405b0/6d6f8a2: BOM page insert + position fix
- 7d202dc/2c05feb/90efe32/0533e5e: alternating orientation, tile decomposition, FADE STEPS fix, camera 45°
- (run 8, 15 commits): COVER_PAGE, FADE_STEPS, HIGHLIGHT_STEP; subject-color masking; Lab palette cache; secondary color by lightness; camera 65°; masonry Z-scan
- (run 9 — partial regression): oscillation removed run-8 LPub3D meta commands
- bcb4382: history injection, LPub3D reference, parse-error retry, test-failure retry
- 689f776: two-stage OR-pool downsampling (shape_fidelity root cause fix)
- (harness refactor): judge+applier architecture, warnings_judge, 340 tests

**Pre-run-10 dim scores (run 9 end state):**
- pdf_completeness: 0 — LPub3D meta commands removed by run-9 oscillation
- instruction_clarity: 1
- build_stability: 2 (1×1 pillars at star arm tips)
- shape_fidelity: 3 (root cause fixed in 689f776)
- reference_fidelity: 4; aesthetics: 5–6; color_match: 7; technical_validity: 5–9

**Harness image-passing note:** `claude -p` does not support `--image`. Images passed as absolute paths in prompt with "Use your Read tool to view this image." LDR content truncated to 400 lines. Advisor timeout 240s, judge/applier timeout 300s/600s.

**`CLAUDE_CODE_OAUTH_TOKEN` note:** Set as Windows user environment variable (not `.env` file). Inherited by `.bat` launcher. Load manually in PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`. The Bash tool does NOT inherit Windows user env vars — always launch harness from PowerShell.

**pytest note:** Use `uv run pytest -q --ignore=tests/integration` for the clean gate. Harness always uses `--ignore=tests/integration`. Integration gate: `BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/ -v`.

**Next action:** Run harness 20 iterations:
```powershell
$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")
$env:PATH += ";C:\Tools\LPub3D"
uv run python tests/harness/run_harness.py --iterations 20
```

## Environment requirements

- Windows 11, Python 3.12+, uv, Node.js 20+
- llama-server running before backend start (port 8080) — text pipeline only; image pipeline (2D silhouette extrusion) works without it and without a GPU
- LDView auto-detected at `C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe` (no PATH needed)
- LPub3D on PATH (`$env:PATH += ";C:\Tools\LPub3D"`) before starting server
- `CLAUDE_CODE_OAUTH_TOKEN` as Windows user environment variable (not `.env`; inherited by `.bat` launcher; load manually in PS: `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`)
- `PYTHONIOENCODING=utf-8` recommended (workspace Unicode print rule)

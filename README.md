# Brickomancer

Takes a photo of a real-world object (or a text description) and produces 3 LEGO build suggestions — compact, standard, and detailed — each with a rendered 3D preview and a parts list. Select one and download a step-by-step instruction book in official LEGO manual style.

Optionally photograph your own LEGO piece pile: Brickomancer identifies the available parts and reports them back with the build. Using that inventory as a soft build constraint is not wired up yet (the suggestion service accepts the inventory but does not yet apply it).

Local-first personal tool. Python/FastAPI backend + React frontend. Clean REST API designed for future migration to a phone or desktop app.

## Stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12, FastAPI, uv |
| Frontend | React 18 + Vite (port 5173) |
| Image → 3D → voxels | rembg (background removal) + Hunyuan3D-2mini (CUDA GPU) + trimesh `voxelized(method="subdivide").fill()` |
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
- `LDView` — auto-detected inside the LPub3D install (`C:\Tools\LPub3D\3rdParty\ldview-4.5\bin\LDView64.exe`, plus the Program Files variants); a standalone `LDView64`/`ldview` on PATH is the fallback, not a requirement
- `LPub3D` on PATH (any of `LPub3D`, `LPub3D.exe`, `lpub3d`, `lpub3d.exe`) — `/api/status` only checks that the binary resolves, it never runs it
- **Image path:** a CUDA GPU + Hunyuan3D-2mini installed in the project venv. `POST /api/generate/from-image` returns a clean 503 if torch/CUDA/`hy3dgen`/weights are unavailable. `hy3dgen` is installed **editable** into the project venv and is deliberately **not** in `pyproject`/lock, so a fresh checkout won't have it — see the image-path step under [Setup](#setup).
- `CLAUDE_CODE_OAUTH_TOKEN` set as a **Windows user environment variable** (not `.env`); load in PowerShell via `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")`

## Setup

```powershell
uv sync
cd frontend; npm install; cd ..
uv run python scripts/download_data.py   # downloads ~50 MB of Rebrickable CSVs + LDConfig.ldr
```

**Image path (optional — needs a CUDA GPU).** `hy3dgen` (Hunyuan3D-2mini) is installed **editable** and is deliberately **not** in `pyproject`/lock, so `uv sync` above won't pull it. Install it into the project venv from the local Hunyuan3D-2 checkout:

```powershell
uv pip install -e C:\Tools\hunyuan-src   # shape-only editable install; NOT in pyproject/lock
```

For a clean-machine reproduction (cu118 torch pin, weights, from-scratch clone), follow the [reproducible install note](docs/investigations/rebuild/04-model-spike-result.md#reproducible-install-what-actually-worked).

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
curl.exe http://localhost:8000/api/status
# {"status":"ok","llama_server_ok":false,"ldview_ok":true,"lpub3d_ok":true}
```

`llama_server_ok` is **vestigial** — the v1 llama-server text path is retired and no request path
depends on the probe, so `false` is the expected value on a correctly configured machine. It stays
in the payload only for the frontend/UAT response contract (`main.py:103-106`, guarded by
`tests/test_main.py`).

## Test

Fast gate — what every change must pass:

```powershell
uv run pytest -q --ignore=tests/integration   # 285 tests
uv run ruff check .
uv run mypy src
npm run build --prefix frontend
```

Slow tier — real services, nothing mocked:

```powershell
$env:BRICKOMANCER_INTEGRATION = "1"
uv run pytest tests/integration/ -v            # 3 smoke tests
```

The image leg of the smoke needs a CUDA GPU and takes ~17 min on the first request in a process
(one-time model load).

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

- **Ephemeral sessions, no database.** All state lives in a per-request `tmp/<uuid>/` directory. The current build keeps the directory (no cleanup) so the LDraw file survives the follow-up `/instructions` call; adding job history later requires only a data-service layer.
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
  models/               schemas.py (Pydantic), brick.py (dataclasses + grid-dim constants
                        + BRICK_PART_IDS / TILE_PART_IDS — single source of truth for
                        build data shape; never re-declare)
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
  test_*.py             unit tests (packer, shapers, services, routes)
  fixtures/             CSV/LDR fixtures + the frozen LPub3D meta header
  harness/              judge, scorer, applier, loop (render-score regression gate)
  integration/          test_smoke.py (gated on BRICKOMANCER_INTEGRATION=1)
scripts/
  download_data.py      fetch Rebrickable CSVs + LDConfig.ldr
  step{4,5,7}_*_uat.py  operator render-verification scripts (LDView / LPub3D / GPU)
documentation/
  rebuild-plan.md       canonical plan of record (13 step blocks, all DONE)
docs/
  follow-ups.md         post-rebuild work register
  investigations/       Phase 0-4 findings (00-verdict .. 06-step4-design)
  rebuild_reference/    archived v1 harness artifacts
  master_plan.md, harness-plan.md, shape-quality-plan.md   superseded v1 plans
```

## Status

**Full rebuild COMPLETE.** All 10 rebuild steps are done — 13 `### Step N` blocks in the plan (Steps 0.1, 0.2-prep and 0.2 are the Phase 0 spike/prep entries, then Steps 1–10), all 13 marked DONE. The completion marker is `15f72e6` (2026-07-15), which is a docs-only commit; the last rebuild *code* landed at `fae2ba1`.

The v1 silhouette+dome image path (which fabricated depth) and the pytest-only quality harness are gone. The project is rebuilt around a `Shaper` seam (`services/shaper.py`, `to_voxels() -> (X, Y, Z)` bool grid) feeding a connectivity-graph brick packer. Both input paths render end-to-end, smoke-verified against the real services.

Gates:

| Command | Result |
|---|---|
| `uv run pytest -q --ignore=tests/integration` | 285 passed (the fast gate) |
| `BRICKOMANCER_INTEGRATION=1 uv run pytest tests/integration/ -v` | 3 further smoke tests, real services (the image leg needs a CUDA GPU) |
| `uv run mypy src` | 0 errors across 22 source files |
| `uv run ruff check .` | 0 violations |

- **Phase 0** — Hunyuan3D-2mini chosen for image→3D (TripoSG install-blocked on Windows); the LPub3D instruction header is BOM-only because `INSERT COVER_PAGE` crashes LPub3D 2.4.9.
- **Phase 1** — in-place clean + the `Shaper` seam; the image/text generate routes were 503-stubbed pending the Shapers.
- **Phase 2 Steps 3–4** — connectivity-graph packer (component / unsupported / articulation analysis) + in-volume bonding. Cube, plus-star and the tested masonry grids pack to 1 connected component, 0 unsupported bricks and **no added build height** (see the minimum-depth exception under Known limits), with masonry ABAB seams preserved. In-volume bonding introduced the bond-only `(2,1)` part — LDraw 3004 rotated 90° about Y, render-verified via `scripts/step4_render_uat.py`.
- **Phase 3 Step 5** — `ImageShaper`: rembg → Hunyuan3D-2mini → trimesh voxelize, wired through `POST /api/generate/from-image`; returns a clean 503 when torch/CUDA/`hy3dgen`/weights are unavailable. `height_studs` is the resolution knob.
- **Phase 3 Step 6** — `TextShaper`: a `claude -p` subprocess emits a sparse 20³ voxel occupancy (strict JSON) → fill/crop → grid, wired through `POST /api/generate/from-text`; returns a clean 503 when the Claude CLI is unavailable. Retires the v1 llama-server text path (no GPU needed).
- **Phase 3 Step 7** — frozen **BOM-only** LPub3D instruction header; fixed a latent crash (`ldraw_writer` still emitted `COVER_PAGE`, which crashes LPub3D 2.4.9). Render-verified: LDView PNG + LPub3D multi-page PDF with BOM.
- **Phase 3 Step 8** — the v1 React wizard already targeted the rebuilt routes (`/from-image`, `/from-text`, `/instructions`) with matching request/response shapes, so no rewiring was needed; `npm run build` is clean (36 modules). `tests/integration/test_smoke.py` was rebuilt to exercise both paths + instructions against the **real** services (nothing mocked), gated on `BRICKOMANCER_INTEGRATION=1`. Live smoke PASSED: text 73 s, **image 1019 s (~17 min, measured before the pipeline cache landed in `f471412`)**, instructions 9 s.
- **Phase 4 Step 9** — rebuilt `tests/harness/` (judge / scorer / applier) around a **render-score regression gate**: apply → pytest → **re-render + re-score** → commit only if nothing regressed, else revert. (v1 committed on pytest-green alone — the plateau cause.) `tests/harness/test_regression_gate.py` proves blanked-PDF → revert, improvement → commit, and the frozen header held in `CONSTRAINTS_TO_PRESERVE` where the judge can never edit it.
- **Phase 4 Step 10** — built the run-loop (`tests/harness/loop.py`) and ran a real 3-iteration calibration on the text eval set. It produced exactly **one scored point** — the iteration-0 baseline, `avg_raw` 8.25 (pdf_completeness 10.0, technical_validity 10.0, build_stability 3.0, part_variety 10.0) — and **zero commits**. Two of the three iterations stopped at the developer step (`SKIPPED_DEV`) and one stopped at the judge stage (`SKIPPED_JUDGE`, on a non-empty `blocking_issues` list rather than a parse failure), so no candidate change ever reached the regression gate. No dimension hit 0 and nothing oscillated, which is what this observation step was watching for, but **the loop does not yet hill-climb**. The pinned cause is the developer step, not scorer saturation — `build_stability` at 3.0 has obvious headroom — because that step round-trips a whole source file through a single-line JSON `content` string, which a ~1000-line file breaks. The judge selected `build_stability` every iteration and reasoned about the real packer code; zero source was mutated. Write-up: [`05-calibration-result.md`](docs/investigations/rebuild/05-calibration-result.md).

Known limits, all recorded and none blocking:

- Minimum-depth slabs (Z=2, plus Y=2 with Z∈{5,9}) still gain +1/+2 layers via the cap fallback, though they stay 1 component / 0 unsupported. Every thick grid (Y≥3 ∧ Z≥3) is zero-added-height.
- The image path's **first** request in a process takes ~17 min, dominated by a one-time `from_pretrained` load of the 7.64 GB Hunyuan3D model (the rest is rembg first-run + 3-tier pack + 3 LDView renders). The pipeline has been cached process-wide since `f471412`, so later requests in the same process skip that load — projected toward ~100 s, but not yet re-measured.
- The harness can gate a change but cannot yet propose one that applies — see the Step 10 developer-step finding above.

Optional follow-ups, none blocking: (1) switch the harness developer step from a whole-file JSON round-trip to a diff/patch or file-write edit, so the calibration loop can actually hill-climb (highest leverage); (2) run the Step 5 live star-survival check (`scripts/step5_star_survival_uat.py`, needs a GPU); (3) point the `/run-harness` skill, still on the v1 harness layout, at `tests/harness/loop.py`. The full register, including untracked backlog items, is [`docs/follow-ups.md`](docs/follow-ups.md); the step-by-step build record is [`documentation/rebuild-plan.md`](documentation/rebuild-plan.md).

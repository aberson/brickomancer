# Task State — Brickomancer

**Task:** Phase 3 rebuild — Shapers behind the Shaper seam
**Status:** Steps 5 (ImageShaper) & 6 (TextShaper) DONE + shipped; ready to start Step 7
**Last written:** 2026-06-21T04:03:01Z
**Session SHA:** 294e4f2

## Current WIP

Nothing in flight. Phase 3 Step 6 (TextShaper, #55) is committed (code `f22acac`, docs `294e4f2`)
and pushed. 267 tests pass, 0 type errors, 0 lint. Both input paths now produce builds end-to-end
(image via Hunyuan3D, text via the Claude CLI). The next unit of work is Step 7.

## Completed (recent)

- **Phase 3 Step 5 (#54):** `ImageShaper` — rembg → Hunyuan3D-2mini → trimesh voxelize → fit →
  `validate_grid`; wired `/api/generate/from-image`; `ModelUnavailableError` → 503. `height_studs`
  is the resolution knob (`max_dim`, clamped `[2,32]`; 28 packs ~66 s/tier, ~10 packs <2 s).
- **Phase 3 Step 6 (#55):** `TextShaper` (`services/text_shaper.py`) — `claude -p`
  (`subprocess_utils.run_claude_text`, OAUTH, no GPU/llama-server) emits a sparse 20³ voxel
  occupancy (strict JSON) → parse/clamp/fill/crop → `validate_grid`. Retries malformed output 3×;
  `TextShaperError` → 503. Wired `/api/generate/from-text` (color defaulted). Retires the v1
  llama-server text path. Tests mock the subprocess through the router.

## Dead ends / superseded

- The pre-rebuild harness ("run-11 / run_harness 20 iterations") is ABANDONED — removed in Phase 1,
  rebuilt fresh in Step 9. Do NOT run `/run-harness` (stale until Step 9). Its orphaned launcher
  `scripts/run_harness.bat` was deleted.
- llama-server is retired (v1 text path). `/api/status` still reports `llama_server_ok` but no path
  uses it — a possible small cleanup, out of Step 6 scope.

## Critical gotchas

- `/from-image` needs a CUDA GPU + Hunyuan3D-2mini in the **project** venv (only in throwaway
  `C:\Tools\spike3d` now; needs 7.64 GB weights) → 503 otherwise.
- `/from-text` needs the `claude` CLI + `CLAUDE_CODE_OAUTH_TOKEN` (Windows user env var, not `.env`;
  the Bash tool does NOT inherit it — load in PowerShell). No GPU.
- Clean gate: `uv run pytest -q --ignore=tests/integration`. Server: `uv run uvicorn --app-dir src
  brickomancer.main:app` (no `--reload`).

## Key files

- `documentation/rebuild-plan.md` § Step 7 — next spec + done-when (3 distinct-parts_count tiers,
  multi-page PDF + BOM page; frozen BOM-only header, no COVER_PAGE).
- `src/brickomancer/services/shaper.py` — seam contract (`to_voxels() -> (X,Y,Z)` bool grid)
- `src/brickomancer/services/{image_shaper,text_shaper}.py` — the two shaper siblings to mirror
- `src/brickomancer/services/suggestion_service.py` + `instruction_service.py` — Step 7 rebuild targets

## Next Action

Start **Phase 3 Step 7 (#56)**: rebuild `suggestion_service` (3 tiers via the OR-pool downsample, not
stride-2) + color assignment + LDView previews + parts list, and wire `instruction_service` to LPub3D
using the **frozen BOM-only meta header** (no COVER_PAGE — crashes LPub3D 2.4.9; render-verified in
Step 0.2). Read `documentation/rebuild-plan.md` § Step 7 first.

## Pending (operator-gated)

- Step 5 **live star-survival** operator Test (top-down ≥4 protrusions, real model) — needs
  Hunyuan3D-2mini in the project venv first.
- Step 6 **live star-recognizable** check — runnable NOW (Claude CLI, no GPU): load the OAUTH token in
  PowerShell, call `from-text "five-pointed star"`, eyeball the build.

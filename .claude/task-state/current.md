# Task State — Brickomancer

**Task:** Phase 3 rebuild — Shapers + suggestion/instruction wiring behind the seam
**Status:** Steps 5, 6, 7 DONE + shipped; ready to start Step 8 (frontend + e2e smoke)
**Last written:** 2026-06-21T04:03:01Z
**Session SHA:** 6d54b55

## Current WIP

Nothing in flight. Phase 3 Step 7 (#56) is committed (`6d54b55`) and pushed. 273 tests pass, 0 type,
0 lint. Both input paths produce builds end-to-end; the instruction PDF path is render-verified
(LDView PNG + LPub3D multi-page PDF + BOM, no crash). The next unit of work is Step 8.

## Completed (recent)

- **Phase 3 Step 5 (#54):** `ImageShaper` — rembg → Hunyuan3D-2mini → trimesh voxelize → fit →
  `validate_grid`; wired `/api/generate/from-image`; `ModelUnavailableError` → 503. `height_studs`
  is the resolution knob (`max_dim`, clamped `[2,32]`; 28 packs ~66 s/tier, ~10 packs <2 s).
- **Phase 3 Step 6 (#55):** `TextShaper` (`services/text_shaper.py`) — `claude -p`
  (`subprocess_utils.run_claude_text`, OAUTH, no GPU/llama-server) emits a sparse 20³ voxel
  occupancy (strict JSON) → parse/clamp/fill/crop → `validate_grid`. Retries malformed output 3×;
  `TextShaperError` → 503. Wired `/api/generate/from-text` (color defaulted). Retires the v1
  llama-server text path. Tests mock the subprocess through the router.
- **Phase 3 Step 7 (#56):** frozen BOM-only LPub3D header. Fixed a latent crash — `ldraw_writer`
  still emitted `0 !LPUB INSERT COVER_PAGE` (crashes LPub3D 2.4.9); now emits `_BOM_META` only (no
  COVER_PAGE/FADE_STEPS). `tests/test_ldraw_writer.py` guards the producer; `scripts/step7_render_uat.py`
  render-verified (LDView PNG + LPub3D 3-page PDF + BOM, no crash). suggestion_service already 3-tier.

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

- `documentation/rebuild-plan.md` § Step 8 — next spec + done-when (npm run build clean; integration
  smoke passes with REAL services for both image + text paths; record image wall-clock).
- `frontend/src/` — v1 React 4-step wizard to port + wire to the rebuilt routes
- `tests/integration/test_smoke.py` — the end-to-end smoke to (re)build
- `src/brickomancer/routers/generate.py` — the wired routes the frontend/smoke hit

## Next Action

Start **Phase 3 Step 8 (#57)**: port the v1 React 4-step wizard + wire to the rebuilt routes; add
`tests/integration/test_smoke.py` exercising the full image AND text paths against a live server with
real services. Done when `npm run build` is clean and the integration smoke passes (image path now
works — Hunyuan3D is installed in the project venv). Read `documentation/rebuild-plan.md` § Step 8.
NOTE: image-path smoke is slow (Hunyuan3D ~100 s+ first run incl. any weight download) — size the
smoke's timeout accordingly. Build in-window/in-place (worktrees lack hy3dgen — it's `pip install -e`,
not in pyproject/lock).

## Pending (operator-gated)

- Step 5 **live star-survival** operator Test (top-down ≥4 protrusions, real model) — needs
  Hunyuan3D-2mini in the project venv first.
- Step 6 **live star-recognizable** check — runnable NOW (Claude CLI, no GPU): load the OAUTH token in
  PowerShell, call `from-text "five-pointed star"`, eyeball the build.

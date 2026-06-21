# Task State — Brickomancer

**Task:** Phase 3 rebuild — Image/Text Shapers behind the Shaper seam
**Status:** Step 5 (ImageShaper, #54) DONE + shipped; ready to start Step 6 (TextShaper, #55)
**Last written:** 2026-06-21T04:03:01Z
**Session SHA:** 54a9913

## Current WIP

Nothing in flight. Phase 3 Step 5 (ImageShaper, #54) is committed (`54a9913`), pushed, and
issue #54 is closed. 253 tests pass, 0 type errors, 0 lint. The next unit of work is Step 6.

## Completed (recent)

- **Phase 3 Step 5 (#54):** `ImageShaper` (`services/image_shaper.py`) behind the Shaper seam —
  rembg → Hunyuan3D-2mini → `trimesh.voxelized(method="subdivide").fill()` → `_fit_to_bounds`
  → `validate_grid`. Wired through `/api/generate/from-image`; `ModelUnavailableError` → clean
  503. `height_studs` is the resolution knob (`max_dim`, clamped `[2,32]`); `max_dim=28` packs
  ~66 s/tier so the route uses `height_studs`. Tests: `test_image_shaper.py` +
  `test_generate_from_image_route.py` (model mocked + a model-unavailable 503).
- **repo-update:** README/CLAUDE.md/plan/memory refreshed; a cross-project lessons-learned entry
  added to the dev/ repo (`ec2c4df`). #54 closed.

## Dead ends / superseded

- The pre-rebuild **"harness run-11 / run_harness 20 iterations"** task (this file's prior
  content) is **ABANDONED** — the v1 harness was removed in Phase 1 and is not rebuilt until
  Step 9. Do NOT resume harness work or run `/run-harness` (stale until Step 9).

## Critical gotchas

- `/from-image` needs a CUDA GPU + Hunyuan3D-2mini in the **project** venv; returns 503 otherwise.
  The model is only in the throwaway `C:\Tools\spike3d` now (project venv needs the 7.64 GB weights).
- Clean gate: `uv run pytest -q --ignore=tests/integration`. Server: `uv run uvicorn --app-dir src
  brickomancer.main:app` (no `--reload`); `CLAUDE_CODE_OAUTH_TOKEN` is a Windows user env var, not `.env`.

## Key files

- `documentation/rebuild-plan.md` § Step 6 — next spec + done-when
- `src/brickomancer/services/shaper.py` — seam contract (`to_voxels() -> (X,Y,Z)` bool grid)
- `src/brickomancer/services/image_shaper.py` — the Step 5 sibling to mirror
- `src/brickomancer/routers/generate.py` — route wiring (`/from-text` is the 503 stub to replace)

## Next Action

Start **Phase 3 Step 6 (#55) — TextShaper**: a Claude CLI subprocess emits a sparse 20³ voxel
occupancy (strict JSON schema) → fill the `(X,Y,Z)` grid behind the same Shaper seam, wired
through `/api/generate/from-text` with an integration test through the router. Read
`documentation/rebuild-plan.md` § Step 6 first; mirror `image_shaper.py`'s structure.

## Pending (operator-gated)

- Step 5 **live star-survival operator Test** (top-down ≥4 protrusions on the real model) — needs
  Hunyuan3D-2mini installed in the project venv first.

# Task State — Brickomancer

**Task:** Brickomancer rebuild — Phase 4 (closed-loop quality harness)
**Status:** Phase 3 COMPLETE (Steps 5–8 shipped); ready to start Phase 4 Step 9 (harness)
**Last written:** 2026-06-21T05:30:00Z
**Session SHA:** 8ed30ca

## Current WIP

Nothing in flight. Phase 3 is complete — both input paths render end-to-end (smoke-verified with
real services). 273 clean-gate tests, 0 type, 0 lint. The next unit of work is Step 9 (Phase 4).

## Completed (recent)

- **Phase 3 Step 5 (#54):** `ImageShaper` — rembg → Hunyuan3D-2mini → voxelize → `validate_grid`;
  `/from-image`; `ModelUnavailableError` → 503. `height_studs` = resolution knob (`max_dim`).
- **Phase 3 Step 6 (#55):** `TextShaper` — `claude -p` sparse 20³ voxel JSON → grid; `/from-text`;
  retries + `TextShaperError`/timeout → 503. Retires the v1 llama-server text path.
- **Phase 3 Step 7 (#56):** frozen BOM-only LPub3D header. Fixed a latent crash — `ldraw_writer`
  still emitted `0 !LPUB INSERT COVER_PAGE` (crashes LPub3D 2.4.9); now `_BOM_META` only.
  `tests/test_ldraw_writer.py` + `scripts/step7_render_uat.py` render-verified.
- **Phase 3 Step 8 (#57):** frontend on current routes (`npm run build` clean);
  `tests/integration/test_smoke.py` rebuilt for real services (gated `BRICKOMANCER_INTEGRATION=1`).
  Smoke PASSED: text 73 s, **image 1019 s (~17 min)**, instructions 9 s.

## Dead ends / superseded / findings

- The pre-rebuild harness ("run-11 / run_harness 20 iters") is ABANDONED — Step 9 rebuilds it fresh.
  Do NOT run `/run-harness` (stale until Step 9); its launcher was deleted.
- llama-server retired; `/api/status` still reports a vestigial `llama_server_ok` (no path uses it).
- **PERF: image path ~17 min/request** — `ImageShaper._load_pipeline` runs `from_pretrained`
  (7.64 GB) on EVERY request. Caching the pipeline as a module singleton is the obvious fix.

## Critical gotchas

- `/from-image` needs CUDA GPU + `hy3dgen` (installed editable from `C:\Tools\hunyuan-src`; NOT in
  pyproject/lock → fresh worktrees lack it; build in-place). Weights in the HF cache. → 503 otherwise.
- `/from-text` needs `claude` CLI + `CLAUDE_CODE_OAUTH_TOKEN` (Windows user env var, not `.env`; the
  Bash tool does NOT inherit it — load in PowerShell). No GPU.
- Clean gate: `uv run pytest -q --ignore=tests/integration`. Integration gate (slow, real services):
  `$env:BRICKOMANCER_INTEGRATION="1"; uv run pytest tests/integration/ -v -s` (PATH += LPub3D, token loaded).
- Server: `uv run uvicorn --app-dir src brickomancer.main:app` (no `--reload`).

## Key files

- `documentation/rebuild-plan.md` § Step 9 — next spec: rebuild the harness so the commit gate is
  rendered-output **score regression** (re-render + re-score with an LLM judge, not pytest alone);
  fixed eval set; frozen meta header in `constraints_to_preserve`. Done-when = a regression-gate test.
- `docs/investigations/rebuild/02-plateau-postmortem.md` + `03-better-approaches.md` §4 — why the
  gate must re-render, not trust pytest.
- `docs/rebuild_reference/` — archived v1 harness reference (for rebuilding fresh).

## Next Action

Start **Phase 4 Step 9 (#58)** — render-scoring harness with a regression gate. Then Step 10
(calibration run, `Type: wait`). Read `documentation/rebuild-plan.md` § Step 9.

## Pending (operator-gated / optional)

- Step 5 **live star-survival** check (top-down ≥4 protrusions on the real model) — model now
  installed, so runnable; but the image path is ~17 min/run.
- **ImageShaper pipeline-caching perf fix** (the ~17 min/request finding above).

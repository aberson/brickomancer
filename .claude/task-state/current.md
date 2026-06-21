# Task State — Brickomancer

**Task:** Brickomancer rebuild — Phase 4 (closed-loop quality harness)
**Status:** Phases 0–3 + Phase 4 Step 9 DONE; only Step 10 (calibration `wait`) remains
**Last written:** 2026-06-21T05:55:00Z
**Session SHA:** c6de8f5

## Current WIP

Nothing in flight. The rebuild is code-complete through Step 9: both input paths render end-to-end
(smoke-verified) and the render-score regression gate is built + tested. 277 clean-gate tests, 0 type,
0 lint. The only remaining step is Step 10 — an operator-run calibration (`Type: wait`).

## Completed (recent)

- **Phase 3 Step 5–8 (#54–57):** ImageShaper, TextShaper, frozen BOM-only LPub3D header (fixed the
  COVER_PAGE crash), frontend + real-services smoke. Both paths render end-to-end.
- **Phase 4 Step 9 (#58):** rebuilt `tests/harness/` (judge / scorer / applier) with the **render-score
  regression gate** — apply → pytest → re-render + re-score → commit-only-if-no-regression-else-revert
  (v1 committed on pytest-green alone, the plateau cause). Judge's COVER_PAGE/FADE_STEPS-offering meta
  reference replaced by `CONSTRAINTS_TO_PRESERVE` (frozen header, never editable).
  `tests/harness/test_regression_gate.py` proves blanked-PDF→revert, improvement→commit,
  frozen-header-in-constraints (fast via injected fakes).

## Dead ends / superseded / findings

- `/run-harness` skill is still STALE (references the v1 harness layout) — the rebuilt harness is
  `tests/harness/` (judge/scorer/applier); the skill needs updating before it can drive Step 10.
- llama-server retired; `/api/status` still reports a vestigial `llama_server_ok` (no path uses it).
- **PERF: image path ~17 min/request** — `ImageShaper._load_pipeline` runs `from_pretrained` (7.64 GB)
  EVERY request. Cache the pipeline as a module singleton (the obvious fix; near-prereq for a usable
  image-eval calibration in Step 10).

## Critical gotchas

- `/from-image` needs CUDA GPU + `hy3dgen` (installed editable from `C:\Tools\hunyuan-src`; NOT in
  pyproject/lock → fresh worktrees lack it; build in-place). Weights in the HF cache. → 503 otherwise.
- `/from-text` needs `claude` CLI + `CLAUDE_CODE_OAUTH_TOKEN` (Windows user env var, not `.env`; the
  Bash tool does NOT inherit it — load in PowerShell). No GPU.
- Clean gate: `uv run pytest -q --ignore=tests/integration`. Integration gate (slow, real services):
  `$env:BRICKOMANCER_INTEGRATION="1"; uv run pytest tests/integration/ -v -s` (PATH += LPub3D, token loaded).
- Harness gate logic is in `tests/harness/applier.py`; `render_and_score` (the slow real path) is in
  `tests/harness/scorer.py` — injectable, so the regression-gate test stays fast.

## Key files

- `documentation/rebuild-plan.md` § Step 10 — next spec: run the harness ~5 iters on the eval set,
  confirm `avg_raw` trends up (v1 was flat 3.5–5.1), record in
  `docs/investigations/rebuild/05-calibration-result.md`. `Type: wait` (operator-run, long).
- `tests/harness/{judge,scorer,applier}.py` — the rebuilt harness to drive the calibration loop.
- `docs/investigations/rebuild/02-plateau-postmortem.md` — why the gate must re-render.

## Next Action

Start **Phase 4 Step 10 (#59) — calibration run (`Type: wait`)**: drive the rebuilt harness for ~5
iterations, confirm the score trend, write `05-calibration-result.md`. Operator-run / long. Recommend
either the ImageShaper pipeline-caching perf fix first OR run calibration on the text eval set (image
is ~17 min/item). The `/run-harness` skill needs updating to the new `tests/harness/` layout first.

## Pending (operator-gated / optional)

- **ImageShaper pipeline-caching perf fix** (~17 min/request finding) — near-prereq for image-eval calibration.
- Step 5 **live star-survival** check (top-down ≥4 protrusions) — model installed, runnable (~17 min/run).
- Update the `/run-harness` skill to the rebuilt `tests/harness/` layout (Step 10 driver).

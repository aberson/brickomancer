# Task State — Brickomancer

**Task:** Brickomancer rebuild — Phase 4 Step 10 calibration (blocked by a scorer crash found this session)
**Status:** ACTIVE — Step 10 still pending. This session shipped 2 goblin-overlap improvements (pushed) and surfaced 2 HIGH findings; the scorer crash BLOCKS the Step 10 calibration until fixed.
**Last written:** 2026-07-14T17:58:24Z
**Session SHA:** 458a09c

## Current WIP

**This session (goblin-overlap improvement pass):** ran an independent 5-lens weakness scan of
brickomancer IN PARALLEL with `/goblin-suggest --small`, then acted on the OVERLAP (items both flagged):
shipped 2 clean ones, parked 1. Both ships are committed + pushed to `origin/master`.

**Immediate next work (agent-completable, offered to operator, NOT yet greenlit):** fix the 2 HIGH
findings below — the `scorer.py:79` crash (unblocks Step 10) and the `vite.config.ts` proxy port. Both
are outside the overlap the operator scoped this pass to, so they were reported, not auto-fixed.

**Tracked project task (unchanged):** Phase 4 Step 10 (#59) — calibration run (`Type: wait`): drive the
rebuilt harness ~5 iters on the eval set, confirm `avg_raw` trends up (v1 flat 3.5–5.1), record in
`docs/investigations/rebuild/05-calibration-result.md`. Operator-run/long. **Now blocked by the scorer
crash** (the harness `render_and_score` throws before scoring the first eval item).

## Completed (recent)

- **Goblin-overlap ship #1 (`54df7dd`):** reconciled the ImageShaper pipeline-caching doc drift. The
  `@lru_cache(maxsize=1)` singleton already landed in `f471412`, but CLAUDE.md (×3), rebuild-plan Step 8,
  and README still called it a "deferred" Step 10 prerequisite. Fixed all; grep confirms zero stale
  "deferred/follow-up" language. (Goblin proposed *adding* the cache; the scan caught it was already done.)
- **Goblin-overlap ship #2 (`458a09c`):** added `scripts/step5_star_survival_uat.py` (mirrors
  step4/step7 operator render-UAT). Runs real ImageShaper on the star fixture → ASCII top-down silhouette
  + advisory protrusion count (`count_protrusions`, validated on synthetic garbage-vs-good anchors:
  filled 4/5/6-pt stars ≥ point count; disk/square/empty → 0) + top-down PNG. GPU run stays operator work.
  Compiled + ruff-clean; helper verified without GPU. (Needs `PYTHONPATH=src` to run, like step7.)
- **Goblin atoms updated (on disk, gitignored):** `sugg-…-add-a-step-5-star-survival` → accepted;
  `sugg-…-cache-imageshaper-…` → declined (already in f471412 — do NOT rebuild);
  `sugg-…-refresh-…-run-harness` → proposed + park note.
- **Prior (pre-session):** Phase 3 Steps 5–8, Phase 4 Step 9 harness (judge/scorer/applier + regression
  gate), ImageShaper perf fix (`f471412`). See git history.

## Dead ends / superseded / findings

- **HIGH — harness scorer crashes on every eval item (`tests/harness/scorer.py:79`).** VERIFIED: line 78
  binds `graph = build_connectivity_graph(placements)` then line 79 calls
  `connected_component_count(graph)`, but `connected_component_count(placements: list[BrickPlacement])`
  (brick_packer.py:492) re-runs `build_connectivity_graph` on its arg → iterating an nx.Graph yields
  node-key tuples → `.x` AttributeError. Line-78 binding is dead. Invisible because every harness test
  injects a fake `render_and_score`. **Blocks Step 10 calibration.** Fix: `connected_component_count(placements)`,
  delete the dead line-78 binding. (~1-line fix + a `_score_pdf`/real-scorer smoke to close the mock-theater gap.)
- **HIGH — Vite dev proxy points at the wrong port (`frontend/vite.config.ts:11,15`).** Proxies `/api`
  and `/static` to `localhost:8001`, but the backend runs on 8000 (CLAUDE.md:31, README). The whole
  wizard ECONNREFUSEDs out of the box. Fix: both targets → `localhost:8000`.
- **Caching finding — RESOLVED + doc-reconciled this session** (was: image path ~17 min/request). The
  `@lru_cache` singleton landed in `f471412`; docs corrected in `54df7dd`. The ~17 min is a one-time
  per-process model load; then inference-only.
- **Other scan findings (medium/low — parked, not yet actioned):** piece-detection runs an expensive
  `claude -p` per photo but the result is discarded (advertised soft-constraint is a no-op); test-count
  drift (CLAUDE.md 277 / README 273 / tree 268); 4 competing plan docs (docs/master_plan.md etc. read as
  live, reference removed v1 modules, no superseded banner); README Status block a phase stale (Step 9
  shown as "next"); frontend a11y gaps (errors not announced, no aria-pressed, unassociated file-input
  labels); dead v1 types (ShapeParams, GenerateImageRequest, unused GenerateTextRequest.height_studs);
  vestigial `llama_server_ok` probe in /api/status; stray root files `1` + `pre-hunyuan-deps.txt`
  (untracked, not gitignored — recurs); `.plan-expedite-state` tracked, should be gitignored.
- `/run-harness` skill (`.claude/skills/run-harness/SKILL.md`) is a full v1 relic (launches removed
  `run_harness.py`, maps dims to removed `image_pipeline.py`, port 8005). Refreshing it to the
  judge/scorer/applier layout is a rewrite (NOT a clean small win) AND blocked by the scorer crash above.
  Parked this session (goblin G2).

## Decisions this session (rejected alternatives kept)

- Ran the independent scan + goblin-suggest as PARALLEL background workflows (not sequential) so the
  overlap is genuinely independent evidence.
- G5: shipped a DOC reconciliation, rejected running `/goblin-do` on the cache atom (would have re-added
  caching that already exists in f471412 — the scan corrected goblin's stale-doc-grounded framing).
- G3: shipped an operator render-UAT script with an advisory (not hard-assert) counter — rejected a CI
  gate, because the plan frames star-survival as a separate operator Test (orientation may need tuning;
  the GPU run can't be CI'd).
- G2: parked, not shipped (v1-relic rewrite + blocked by the scorer crash).
- Committed direct-to-master (brickomancer's established solo-repo convention), not a feature branch.
- Acted on the OVERLAP only (operator scope); the 2 HIGH non-overlap findings were reported + offered.

## Critical gotchas

- `/from-image` needs CUDA GPU + `hy3dgen` (editable from `C:\Tools\hunyuan-src`; NOT in pyproject/lock →
  fresh worktrees lack it; build in-place). Weights in HF cache. → clean 503 otherwise.
- `/from-text` needs `claude` CLI + `CLAUDE_CODE_OAUTH_TOKEN` (Windows user env var, not `.env`; Bash
  tool does NOT inherit it — load in PowerShell). No GPU.
- Scripts are src-layout: run with `$env:PYTHONPATH="src"` (step5/step7 note this).
- Clean gate: `uv run pytest -q --ignore=tests/integration`. Integration gate (slow, real services):
  `$env:BRICKOMANCER_INTEGRATION="1"; uv run pytest tests/integration/ -v -s`.

## Key files

- `tests/harness/scorer.py:78-79` — the HIGH crash to fix first (unblocks Step 10).
- `frontend/vite.config.ts:11,15` — proxy port 8001→8000.
- `scripts/step5_star_survival_uat.py` — new operator UAT (this session).
- `documentation/rebuild-plan.md` § Step 10 — calibration spec (Type: wait).
- Full 28-finding scan: was in an ephemeral scratchpad task file (now gone) — the load-bearing items are
  captured in § Findings above.

## Next Action

Present the 2 HIGH findings to the operator and get their call:
1. **Fix `tests/harness/scorer.py:79`** (pass `placements` not `graph`; drop the dead line-78 binding) —
   unblocks the Step 10 calibration. Add a real-scorer smoke test to close the mock-theater gap.
2. **Fix `frontend/vite.config.ts`** proxy 8001→8000 — the wizard is dead out of the box otherwise.
If the operator greenlights, do both with narrow tests; then Step 10 calibration is unblocked (run on the
text eval set to avoid the ~17 min/item image path). If not, the tracked task remains Step 10 (`Type: wait`,
operator-run). Lower-severity scan findings are parked in § Findings.

## Pending (operator-gated / optional)

- Step 5 **live star-survival** check — now scriptable via `scripts/step5_star_survival_uat.py` (needs
  CUDA + weights, ~min/run; operator-run).
- `/run-harness` skill refresh to the rebuilt `tests/harness/` layout — after the scorer crash is fixed.
- Delete stray root files `1` + `pre-hunyuan-deps.txt`; gitignore `.plan-expedite-state` + `.pytest_cache/`.

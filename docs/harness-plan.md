# Brickomancer — Instruction Quality Hill-Climbing Harness Plan

## 1. What This Feature Does

This feature adds a self-improving testing harness that iteratively improves the visual
and structural quality of Brickomancer's generated LEGO instruction PDFs. Each iteration
runs the full pipeline end-to-end (TripoSR → brick packing → LDraw → LDView previews →
LPub3D PDF), then spawns seven parallel advisor subagents — each scoring one quality
dimension — and uses a weighted-random selector to pick the weakest dimension, feed its
findings to a developer subagent, and apply one targeted code change. Changes are
auto-committed to git so the run is a fully-traceable hill-climbing history. The harness
exits after N iterations (default 5) or when the operator kills it; it logs prominently
if advisors' average score suggests early completion.

The triggering motivation: the current pipeline produces structurally valid but visually
poor output — monochrome gray rectangular blobs for organic subjects like cakes, no
new-brick highlighting, no BOM page, fixed-angle LDView renders — all problems invisible
to the existing unit test suite.

## 2. Existing Context

Phase 1 (Steps 1–11) is complete. The full pipeline is operational:

- **`image_pipeline.py`:** TripoSR → trimesh voxelization (subdivide + fill). Always
  produces orthogonal box-quantized shapes; no shape classification or organic-part
  selection. Voxel pitch is `_STUD_METERS = 0.0096`.
- **`brick_packer.py`:** Rectangular brick types only: `(2×4), (2×3), (2×2), (1×4),
  (1×3), (1×2), (1×1)`. Masonry offset alternates per layer. Connectivity repair post-
  packing. No slopes, curves, or round plates in the vocabulary.
- **`ldraw_writer.py`:** Sorts by `(y, x, z)`, batches 8 bricks/step, inserts `0 STEP`
  markers. Single uniform color per suggestion (dominant color from image). No new-brick
  callouts, no BOM meta-commands, no per-step part annotations.
- **`subprocess_utils.py`:** LPub3D called as `LPub3D -pe pdf <ldr_path>` — minimal
  flags, no BOM, no annotation options. LDView renders at 400×300 fixed camera angle.
- **`suggestion_service.py`:** Three tiers (compact/standard/detailed). Compact uses
  2× downsampling; detailed restricts to `(1×2)` and `(1×1)`. All tiers share the
  dominant color.
- **`routers/generate.py`:** `POST /api/generate/from-image` accepts `image` (file),
  optional `piece_images[]`, `height_studs` (default 10). Returns
  `GenerateResponse{suggestions: list[Suggestion]}` where `Suggestion` shape is:
  `{id: str, tier: str, preview_url: str, parts_count: int, parts_list: list[PartCount]}`.
  `Suggestion.id` IS the `suggestion_id`. `tier` is one of `"compact"` / `"standard"` /
  `"detailed"` (tier_index 0 / 1 / 2). `POST /api/generate/instructions`
  accepts `{suggestion_id: "<uuid>_<tier_index>"}` (e.g. `"<uuid>_0"` for compact),
  returns `application/pdf`.
- **`tests/integration/test_smoke.py`:** Hits `localhost:8000`. All tests guarded with
  `pytest.mark.skipif` for service availability.
- **`docs/master_plan.md`:** Steps 1–11 + Step M1 (UAT). This plan continues from
  Step 12.

## 3. Scope

**In scope:**
- `tests/harness/run_harness.py` — main loop script (server lifecycle, iteration loop,
  scoring, developer agent invocation)
- `tests/harness/advisors.yaml` — versioned advisor prompts with anchor examples (7
  dimensions)
- `tests/harness/runs/` — per-iteration artifact bundles (PDF, previews, reports)
- `tests/harness/scores.jsonl` — iteration history (scores, changes, timestamps)
- Any source file the developer agent modifies during a harness run (all files in scope)
- Port 8005 owned exclusively by the harness; does not touch port 8000/8001

**Out of scope:**
- Frontend UI changes
- New API endpoints
- Automated CI integration (harness is a manual operator tool for now)
- Multi-image or batch input (harness uses `cake.jpg` as canonical input)
- Text pipeline testing (image pipeline only for harness v1)

## 4. Impact Analysis

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `src/brickomancer/services/ldraw_writer.py` | modify | Developer agent target: step grouping, Bill of Materials (BOM) meta-commands, new-brick Buffer Exchange (BUFEXCHG — LDraw syntax for highlighting new parts per step) markers | glob confirmed: 1 file, `sequence_steps()` and `write_ldr()` are the primary targets |
| `src/brickomancer/services/brick_packer.py` | modify | Developer agent target: brick type vocabulary, masonry logic | glob confirmed: 1 file, `BRICK_TYPES` list is the expansion point |
| `src/brickomancer/utils/subprocess_utils.py` | modify | Developer agent target: LPub3D flags, LDView camera/resolution | glob confirmed: 1 file, `run_ldview()` and `run_lpub3d()` are the targets |
| `src/brickomancer/services/suggestion_service.py` | modify | Developer agent target: multi-color support across tiers | glob confirmed: 1 file |
| `src/brickomancer/services/image_pipeline.py` | modify | Developer agent target: shape classification, voxelization method | glob confirmed: 1 file |
| `tests/integration/test_smoke.py` | read-only | Harness references its skip-guard patterns; BASE_URL stays at 8000 | grep confirmed: `BASE_URL = "http://localhost:8000"` — harness uses 8005 exclusively |

No shared constants or function signatures are changed by the harness scaffolding itself.
The developer agent may change any of the above files during a run; each change is a
git commit, so all modifications are traceable and reversible.

## 5. New Components

### `tests/harness/run_harness.py`

Main loop script. Responsibilities:

1. **Server lifecycle:** Start uvicorn on port 8005 via subprocess (`uv run uvicorn
   --app-dir src brickomancer.main:app --port 8005`). Poll `/api/status` until ready
   (max 60s). On exit, terminate the subprocess.
2. **Iteration loop (N times, default 5):**
   a. POST to `http://localhost:8005/api/generate/from-image` with `cake.jpg` +
      `height_studs=8`, capture `suggestion_id` for compact tier (`<uuid>_0`).
   b. POST to `http://localhost:8005/api/generate/instructions` with the compact
      `suggestion_id`, save PDF to `tests/harness/runs/iteration_N/instructions.pdf`.
   c. Copy preview PNG from `tmp/<uuid>/suggestion_0_preview.png` to
      `tests/harness/runs/iteration_N/preview.png`.
   d. Spawn 7 advisor subagents in parallel (see §advisors.yaml). Each receives the
      PDF path, preview PNG path, LDR file path, original `cake.jpg` path, and its
      prompt from `advisors.yaml`.
   e. Collect `{score: 0–10, confidence: 0–1, findings: [...]}` from each advisor.
   f. Normalize scores (z-score across the 7, clamp back to [0,10]).
   g. Save full raw + normalized report to
      `tests/harness/runs/iteration_N/advisor_reports.json`.
   h. Append normalized scores + metadata to `tests/harness/scores.jsonl`.
   i. Compute weighted distribution (weight = 10 − normalized_score × confidence).
      Sample one dimension.
   j. Invoke developer subagent with: selected advisor's findings, relevant source
      file(s), instruction to make exactly one targeted change.
   k. Developer agent writes the change; harness runs `uv run pytest -q --tb=short`
      as a quality gate.
   l. If tests pass: `git add <modified_files> && git commit -m "harness iter N:
      improve <dimension>"`. The developer agent returns the list of modified
      files; stage only those (never `git add -A`).
      If tests fail: log failure, revert change (`git checkout -- .`), mark iteration
      as `SKIPPED_REVERT` in scores.jsonl.
   m. Log average normalized score. If average > 8.0 (configurable), print prominent
      `[HARNESS] Advisors suggest quality target met — continuing to iteration N/N`.
3. **Shutdown:** terminate server, print summary table of scores across all iterations.

### `tests/harness/advisors.yaml`

Versioned advisor prompt library. Schema:

```yaml
version: "1.0"
advisors:
  - id: shape_fidelity
    name: "Shape Fidelity"
    reads: [preview_png, input_image]
    prompt: |
      <full prompt text with rubric and anchor examples>
    anchors:
      - score: 2
        description: "No resemblance to input — rectangular blob"
      - score: 5
        description: "Rough proportions match but details lost"
      - score: 8
        description: "Clear resemblance, distinct features visible"
```

Seven advisors (see Design Decisions §6.3 for full prompt outlines):

| ID | Name | Reads |
|---|---|---|
| `shape_fidelity` | Shape Fidelity | preview_png, input_image |
| `part_variety` | Part Variety & Organic Fit | preview_png, parts_list |
| `build_stability` | Build Stability | ldr_file |
| `instruction_clarity` | Instruction Clarity | pdf, preview_png |
| `aesthetics` | Aesthetics | preview_png, pdf_first_page, input_image |
| `pdf_completeness` | PDF Completeness | pdf |
| `technical_validity` | Technical Validity | ldr_file, parts_list |

### `tests/harness/runs/iteration_N/`

Per-iteration artifact bundle:
```
runs/
  iteration_1/
    instructions.pdf       # Full LPub3D PDF
    preview.png            # LDView compact preview
    advisor_reports.json   # Raw + normalized scores for all 7 advisors
  iteration_2/
    ...
```

`advisor_reports.json` shape:
```json
{
  "iteration": 1,
  "advisors": {
    "shape_fidelity": {
      "score_raw": 3.2,
      "score_normalized": 2.8,
      "weight": 6.48,
      "confidence": 0.9,
      "findings": ["No resemblance to input — rectangular blob"]
    }
  },
  "avg_raw": 5.1,
  "avg_normalized": 4.9
}
```
Keys under `advisors` are the 7 advisor IDs from `advisors.yaml`. `weight = (10 - score_normalized) × confidence`.

### `tests/harness/scores.jsonl`

One JSON line per iteration:
```json
{"iteration": 1, "timestamp": "2026-06-12T19:00:00Z", "scores_raw": {"shape_fidelity": 3.2, ...}, "scores_normalized": {"shape_fidelity": 2.8, ...}, "selected_dimension": "shape_fidelity", "change_summary": "Added slope brick types for organic shapes", "test_result": "PASS", "avg_normalized": 4.1}
```

## 6. Design Decisions

### 6.1 Full pipeline per iteration (including TripoSR)

Shape fidelity is a first-class quality dimension alongside PDF formatting. The input
image → 3D shape → brick vocabulary chain is where the cake-as-blob problem originates.
Skipping TripoSR would hide that entire class of improvement. The 30–60s per iteration
cost is accepted; the harness is a slow overnight tool, not a fast feedback loop.

### 6.2 Weighted random selector with bias toward lowest scores

Rather than always picking the lowest-scoring dimension (which would over-optimize one
axis), the harness samples from a weighted distribution where lower-scoring dimensions
are more probable. Weight formula: `w = (10 − normalized_score) × confidence`. This
allows any dimension to be selected, prevents over-focus, and naturally distributes
improvement across axes over N iterations.

### 6.3 Advisor calibration: anchor examples + z-score normalization + confidence

Three-layer defense against systematic bias:
1. **Anchor examples** in each prompt (scores 2, 5, 8) anchor the scale so advisors
   calibrate to the same range.
2. **Z-score normalization** across the 7 scores removes systematic per-advisor bias
   (a harsh advisor who scores 2–4 and a lenient one scoring 6–9 both influence
   the distribution equally after normalization).
3. **Confidence field** `(0–1)` down-weights low-confidence scores in the sampling
   distribution without discarding them from the report.

Full reports (raw, pre-normalization) are saved to `advisor_reports.json` for human
review.

### 6.4 Developer agent: targeted one-change discipline

The developer subagent receives: the selected dimension's full advisor report, the
source file(s) most relevant to that dimension (per a static mapping in
`run_harness.py`), and the instruction "make exactly one targeted change." One change
per iteration keeps the hill-climbing signal clean — if the tests pass and the next
iteration scores better, the change was beneficial. If tests fail, the harness reverts
and marks the iteration SKIPPED_REVERT.

Dimension → primary files mapping (static):
- `shape_fidelity` → `image_pipeline.py`
- `part_variety` → `brick_packer.py`
- `build_stability` → `brick_packer.py`, `ldraw_writer.py`
- `instruction_clarity` → `ldraw_writer.py`
- `aesthetics` → `suggestion_service.py`, `subprocess_utils.py`
- `pdf_completeness` → `ldraw_writer.py`, `subprocess_utils.py`
- `technical_validity` → `ldraw_writer.py`, `brick_packer.py`

### 6.5 Auto-commit per iteration

Every passing iteration is committed to git: `git commit -m "harness iter N: improve
<dimension>"`. This makes `git log` a complete record of the hill-climbing run and
every change is trivially reversible with `git revert` or `git reset`.

### 6.6 Port 8005 owned by harness

The harness starts and stops uvicorn on port 8005 exclusively. This avoids conflicts
with the interactive dev server (8000/8001). The harness sets `$env:PATH +=
";C:\Tools\LPub3D"` before starting uvicorn to ensure LPub3D is available.

### 6.7 Claude reads PDFs natively

Advisor subagents that score PDF content (instruction_clarity, pdf_completeness,
aesthetics) pass the PDF file path directly to the Claude subagent via the Read tool.
Claude can read PDFs natively — no `pdftoppm` or Pillow conversion needed. Advisors
that need the LDR file read it as plain text.

## 7. Build Steps

<!-- autofix-applied: 2026-06-12 -->
### Step 12: Advisor prompt library
- **Problem:** Write `tests/harness/advisors.yaml` with all 7 advisor prompts. Each
  must include: a clear scoring rubric with explicit criteria, three anchor examples
  (score 2 / score 5 / score 8 with concrete descriptions), a confidence guidance
  section, and a structured output spec `{score: int, confidence: float, findings:
  list[str]}`. Prompts should be self-contained — a fresh model with no context can
  score a LEGO instruction PDF against them. Dimensions: shape_fidelity,
  part_variety, build_stability, instruction_clarity, aesthetics, pdf_completeness,
  technical_validity. See §5 for the YAML schema and §6.3 for calibration requirements.
- **Type:** code
- **Issue:** #17
- **Flags:** --reviewers code
- **Produces:** `tests/harness/advisors.yaml`
- **Done when:** All 7 advisors present, each has a rubric + 3 anchors + structured
  output spec; `pytest tests/harness/test_advisors.py` passes (schema validation)
- **Depends on:** none
- **Status:** DONE (2026-06-12)

<!-- autofix-applied: 2026-06-12 -->
### Step 13: Harness scaffolding — server lifecycle and iteration loop
- **Problem:** Write the skeleton of `tests/harness/run_harness.py`. Must handle:
  server start (uvicorn on port 8005, `$env:PATH` including `C:\Tools\LPub3D`,
  poll `GET /api/status` until HTTP 200 with `ldview_ok: true` AND `lpub3d_ok: true`,
  max 60s timeout; full response shape: `{status: str, llama_server_ok: bool,
  ldview_ok: bool, lpub3d_ok: bool}`), iteration loop (N=5 default,
  configurable via CLI arg `--iterations N`), per-iteration artifact directory
  creation (`tests/harness/runs/iteration_N/`), `scores.jsonl` append, prominent
  logging when avg score > 8.0, clean server shutdown on exit or exception. Stub
  out the pipeline executor, advisor engine, and developer agent as `TODO` function
  calls so the skeleton is runnable end-to-end without them.
- **Type:** code
- **Issue:** #18
- **Flags:** --reviewers code
- **Produces:** `tests/harness/run_harness.py` (skeleton), `tests/harness/runs/`
  (directory), `tests/harness/scores.jsonl` (created on first run)
- **Done when:** `python tests/harness/run_harness.py --iterations 1 --dry-run`
  completes without error (dry-run skips actual API calls), server starts and stops
  cleanly on port 8005, scores.jsonl is created with a stub entry
- **Depends on:** 12
- **Status:** DONE (2026-06-12)

<!-- autofix-applied: 2026-06-12 -->
### Step 14: Pipeline executor — API call, PDF download, artifact collection
- **Problem:** Implement the pipeline executor in `run_harness.py`. For each iteration:
  POST to `http://localhost:8005/api/generate/from-image` with
  `tests/integration/fixtures/cake.jpg` and `height_studs=8`; extract the compact
  suggestion (`tier="compact"`) from the response; POST to
  `/api/generate/instructions` with its `suggestion_id`; save the returned PDF to
  `runs/iteration_N/instructions.pdf`; copy the preview PNG from the temp dir to
  `runs/iteration_N/preview.png`; record the LDR file path for advisor use. Handle
  HTTP errors, timeout (max 300s for generate, 120s for instructions), and missing
  preview PNG gracefully — log but continue the iteration.
- **Type:** code
- **Issue:** #19
- **Flags:** --reviewers code
- **Produces:** `runs/iteration_N/instructions.pdf`, `runs/iteration_N/preview.png`,
  LDR path captured in iteration state dict
- **Done when:** Running `python tests/harness/run_harness.py --iterations 1` with
  server already up on 8005 produces a non-empty PDF at
  `runs/iteration_1/instructions.pdf` and a non-empty `preview.png`
- **Depends on:** 13
- **Status:** DONE (2026-06-13)

<!-- autofix-applied: 2026-06-12 -->
### Step 15: Multi-advisor review engine
- **Problem:** Implement the advisor engine in `run_harness.py`. For each iteration,
  after artifact collection: load `advisors.yaml`; spawn all 7 advisor subprocess
  calls in parallel (`ThreadPoolExecutor(max_workers=7)`), each running `claude -p
  <prompt>` with `CLAUDE_CODE_OAUTH_TOKEN` (same pattern as `run_claude_subprocess`
  in `subprocess_utils.py`); for advisors that read images, add `--image <path>`;
  for advisors that read LDR files, embed file text in the prompt body; for PDF
  readers, embed the PDF path — Claude reads PDFs natively; collect
  `{score, confidence, findings}` from each;
  apply z-score normalization across the 7 raw scores then clamp to [0,10]; compute
  sampling weights `w = (10 − normalized_score) × confidence`; save the full report
  (raw scores, normalized scores, weights, all findings) to
  `runs/iteration_N/advisor_reports.json`. Advisors that fail or time out (30s)
  return `{score: 5, confidence: 0, findings: ["ADVISOR_TIMEOUT"]}` so the loop
  continues. Append normalized scores to `scores.jsonl` entry.
- **Type:** code
- **Issue:** #20
- **Flags:** --reviewers code
- **Produces:** `runs/iteration_N/advisor_reports.json` per iteration, scores in
  `scores.jsonl`
- **Done when:** Running 1 iteration produces a valid `advisor_reports.json` with all
  7 advisors present, raw + normalized scores, weights; `pytest tests/harness/
  test_advisor_engine.py` passes (unit tests for normalization + weight computation)
- **Depends on:** 12, 14
- **Status:** DONE (2026-06-13)

<!-- autofix-applied: 2026-06-12 -->
### Step 16: Weighted selector + developer agent integration
- **Problem:** Implement the final loop stage in `run_harness.py`. After advisor
  scoring: sample one dimension using the weighted distribution from Step 15; look up
  the primary source files for that dimension (per the static mapping in §6.4); invoke
  a developer subprocess call (`claude -p <prompt>` with `CLAUDE_CODE_OAUTH_TOKEN`,
  same auth pattern as piece_detector) with: the selected advisor's full findings,
  the content of the relevant source file(s) embedded in the prompt, and the
  instruction "output a JSON object `{changes: [{file_path, content}], summary:
  str}` where each entry is the complete new content of a modified file — make
  exactly one targeted change to improve <dimension>"; harness writes those files
  to disk from the JSON output; run `uv run pytest -q --tb=short` as a quality
  gate; if tests pass, `git add <modified_file_paths>` (from `changes[].file_path`)
  + `git commit -m "harness iter N: improve <dimension> (score was X.X/10)"`;
  if tests fail, `git checkout -- .` + log revert + mark iteration
  `SKIPPED_REVERT` in scores.jsonl. After commit or revert, append `change_summary`
  and `test_result` to the iteration's scores.jsonl entry.
- **Type:** code
- **Issue:** #21
- **Flags:** --reviewers code
- **Produces:** Complete `run_harness.py`, one git commit per passing iteration
- **Done when:** Running `python tests/harness/run_harness.py --iterations 2`
  completes both iterations: PDFs generated, advisor reports saved, developer agent
  makes a change on each iteration, passing iterations are committed to git,
  `scores.jsonl` has 2 entries with all fields populated
- **Depends on:** 15
- **Status:** DONE (2026-06-13)

### Step 17: Smoke gate — two-iteration end-to-end run
- **Problem:** Operator runs the harness for 2 full iterations against `cake.jpg`
  and verifies the complete loop works. Confirm: server starts cleanly on 8005,
  API call succeeds (3 suggestions returned), PDF and preview saved to `runs/`,
  at least 5 of 7 advisors return structured responses (not ADVISOR_TIMEOUT),
  developer agent makes a change on each iteration, at least one iteration commits
  to git, `scores.jsonl` has 2 well-formed entries.
- **Type:** operator
- **Issue:** #22
- **Produces:** `runs/iteration_1/` and `runs/iteration_2/` with full artifact
  bundles, 2 entries in `scores.jsonl`
- **Done when:** Operator confirms all checklist items above; no unhandled exceptions
  in harness output
- **Depends on:** 16
- **Status:** DONE (2026-06-13)

### Step 18: Advisor calibration review
- **Problem:** Operator reads `runs/iteration_1/advisor_reports.json` and
  `runs/iteration_2/advisor_reports.json` and sanity-checks advisor scores. Look for:
  any advisor consistently scoring 9–10 (too lenient), any advisor consistently
  scoring 1–2 (too harsh), any advisor where the narrative findings contradict the
  numeric score, any ADVISOR_TIMEOUT entries. Update anchor examples in
  `advisors.yaml` for any miscalibrated advisor. Re-run 1 iteration to confirm
  adjustments take effect.
- **Type:** operator
- **Issue:** #23
- **Produces:** Updated `advisors.yaml` (if calibration needed), git commit with
  calibration changes
- **Done when:** Operator satisfied that all 7 advisor scores are plausibly
  calibrated; no advisor has a score that contradicts its findings narrative
- **Depends on:** 17
- **Status:** DONE (2026-06-13)

## 8. Risks and Open Questions

| Item | Risk | Mitigation |
|---|---|---|
| TripoSR inference time | 30–60s per iteration × 5 = 3–5 min minimum | Accepted; harness is an overnight tool not a fast loop |
| Developer agent makes a change that breaks the API contract | Tests catch it; harness reverts | `uv run pytest -q` quality gate + `git checkout -- .` on failure |
| Advisor calibration drift | Advisors may score differently as they improve or as the output improves | Step 18 calibration review; `advisor_reports.json` human-readable for ongoing sanity checks |
| Developer agent makes circular changes | Improves dimension X, then later reverts it | `scores.jsonl` tracks history; operator can inspect `git log` and cherry-pick best commit |
| LPub3D not on PATH in harness subprocess | Server starts but PDF generation fails | Harness sets `$env:PATH += ";C:\Tools\LPub3D"` before spawning uvicorn |
| Port 8005 already in use | Harness fails to start server | Harness checks port availability before starting; errors clearly |
| `claude -p` subprocess rate limits | Advisor engine spawns 7 parallel subprocess calls per iteration via `CLAUDE_CODE_OAUTH_TOKEN` | 7 calls/iteration well within OAuth tier limits; add retry with backoff if needed |
| `transformers<5.0.0` constraint | Future `uv sync` might upgrade transformers and break TripoSR | Constraint documented in CLAUDE.md; not a harness concern but noted |

## 9. Testing Strategy

**New tests created by this feature:**

- `tests/harness/test_advisors.py` — validates `advisors.yaml` schema: all 7 advisors
  present, each has `prompt`, `anchors` (3 entries at scores 2/5/8), `reads` list,
  structured output spec. Pure file validation, no LLM calls.
- `tests/harness/test_advisor_engine.py` — unit tests for normalization and weight
  computation: z-score normalization with known inputs, weight formula, edge cases
  (all same score → uniform weights, one zero-confidence advisor → zero weight).

**Existing tests:**

- `tests/integration/test_smoke.py` — unchanged; uses port 8000. Harness uses 8005.
  No conflict.
- `uv run pytest -q --ignore=tests/integration` — run as quality gate after each developer agent change.
  303 passing tests must stay passing.

**End-to-end verification:**

Step 17 (smoke gate) is the primary integration test for the harness itself. It verifies
the full loop works with real TripoSR inference, real LPub3D PDF generation, and real
advisor scoring. This is deliberately an operator step — the harness cannot test itself
automatically without running the full 30–60s TripoSR pipeline.

---

## 10. Post-Build Fixes (2026-06-13)

Three bugs found during first full harness run, all fixed before overnight hill-climbing.

### Bug A — pytest gate blocked by integration smoke tests

**Symptom:** Every developer change was reverted (`SKIPPED_REVERT`). The harness pytest gate ran `uv run pytest -q --tb=short` with no exclusions. The two integration smoke tests (`test_smoke.py`) hit `localhost:8000`, which was occupied by an orphaned server from a prior session, and returned HTTP 503 (TripoSR not loaded). Both tests failed on every gate invocation, regardless of developer changes.

**Fix:** Added `--ignore=tests/integration` to the pytest invocation. Also added failure logging (stdout/stderr of pytest printed to harness log on non-zero exit). Commit: `957c55f`.

### Bug B — quality gate unreachable (avg_normalized always 5.0)

**Symptom:** `QUALITY_THRESHOLD = 8.0` was checked against `avg_normalized`, which is always exactly 5.0 by construction (z-score normalization forces the mean to 5.0). The gate could never trigger. Additionally, the gate had a log message but no `break` — it would have logged and continued even if the condition somehow fired.

**Fix:** Changed threshold check to use `avg_raw` (mean of the 1–7 raw advisor scores). Added `break` on threshold met. Added `avg_raw` field to `scores.jsonl` entries and to the in-memory `advisor_results` report. Commit: `696593c`.

### Bug C — stray LDView POV-Ray file in project root

**Symptom:** LDView generated a `1` file (POV-Ray scene source) in the project root during an earlier harness run. This was an untracked file picked up by `git status`.

**Fix:** Deleted the file.

### `/run-harness` skill added

After diagnosing the above, a `/run-harness` skill was written at `.claude/skills/run-harness/SKILL.md`. It handles pre-flight checks, displays a run-config panel (image thumbnail, baseline scores with trend arrows, source file map), waits for "go", launches the harness in the background, and posts status updates at 30s / 1m / 2m / 5m then every 10 min. Includes clickable PDF links per completed iteration and auto-pushes on completion. Commit: `8c1688f`.

## Session notes — 2026-06-13

### Completed this session

Steps 12–16 built and merged. Desktop launcher (`scripts/run_harness.bat`) created.
302 tests, 0 type errors, 0 lint violations.

### Step 17 UAT run — bugs found (2026-06-13)

First harness run with default 5 iterations. Pipeline executor succeeded (PDF 469 KB, preview PNG copied). Advisor engine encountered two bugs:

**Bug 1 — `--image` flag not recognised by installed claude CLI**

Affects: shape_fidelity, aesthetics, part_variety, instruction_clarity (all add `--image <path>` for preview_png or input_image reads).

```
[HARNESS] Advisor shape_fidelity exited 1: error: unknown option '--image'
[HARNESS] Advisor aesthetics exited 1: error: unknown option '--image'
[HARNESS] Advisor part_variety exited 1: error: unknown option '--image'
[HARNESS] Advisor instruction_clarity exited 1: error: unknown option '--image'
```

Fix needed: investigate the correct image-passing mechanism for `claude -p` in the installed version (`claude --help`). Likely options: different flag name, stdin pipe, or base64-in-prompt.

**Bug 2 — LDR-file advisors timeout at 30s**

Affects: build_stability, technical_validity (embed full LDR file text in prompt body).

```
[HARNESS] Advisor technical_validity timed out after 30s
[HARNESS] Advisor build_stability timed out after 30s
```

Fix needed: raise `ADVISOR_TIMEOUT_S` (try 120s), or truncate/summarise LDR content before embedding (LDR files can be 1000+ lines).

**What did work:**

- pdf_completeness (reads [pdf] only — no --image, no LDR embed) returned real score 4 with findings
- Developer agent correctly selected pdf_completeness (lowest normalized score)
- Claude proposed: "Add LPub3D COVER_PAGE and BOM meta-commands to the LDraw file"
- Change was applied to ldraw_writer.py; pytest failed (SKIPPED_REVERT); file reverted cleanly

### Fixes applied (2026-06-13)

**Bug 1 — `--image` replaced with Read-tool-in-prompt approach**

Images now passed as absolute paths appended to prompt_parts before full_prompt assembly:
```
"\n\nThe rendered LEGO preview image is at this absolute path: {preview_png}\n"
"Use your Read tool to view this image."
```
Same fix applied to `subprocess_utils.run_claude_subprocess` (piece detector). Test `test_command_format` updated to assert `--image` absent.

**Bug 2 — Timeouts and LDR truncation**

- `ADVISOR_TIMEOUT_S`: 30 → 240s
- `DEVELOPER_TIMEOUT_S`: 120 → 300s
- LDR content truncated to 400 lines before embedding (was causing oversized prompts for `build_stability`)

Note: Pages-parameter PDF read was tried but broke PDF reading (requires `pdftoppm`, not available on this system). Reverted to full-content read.

### Step 17 re-run result (2026-06-13)

7/7 advisors completed with real scores. Developer agent ran full loop (wrote change, tests failed, reverted cleanly). Representative scores: part_variety=1 (correct — build uses 4 rectangular brick types only), technical_validity=6–7, pdf_completeness=4, shape_fidelity=2–3.

### Step 18 calibration result (2026-06-13)

No calibration changes needed. All advisors returned scores in 1–7 range with findings that narratively match the scores. `part_variety` scoring 1 consistently is correct, not miscalibration — the cake build uses only 4 rectangular brick types. No advisor scored 9–10 (too lenient). `advisors.yaml` unchanged.

---

## 11. First Harness Run + Quality Improvements (2026-06-13)

### First real run — 5 iterations (cake.jpg)

All 5 iterations ran with real advisor scores (7/7 advisors returning real results). One change committed: connectivity_repair deduplication logic in `brick_packer.py` (bce997b). Remaining 4 iterations: 3 SKIPPED_REVERT (pytest failed), 1 SKIPPED_PARSE_ERROR (developer agent JSON truncated due to file size).

**Honest assessment:** Very little quality improvement across 5 iterations.

Root cause: `part_variety` advisor consistently scored 1/7 (correct — the cake build uses only 4 rectangular brick types). Since z-score weighting almost always selected `part_variety`, the developer agent spent every iteration trying to diversify brick types — an architectural constraint that can't be solved by tweaking `brick_packer.py` without changing voxelization resolution or the overall packing strategy. The lowest-hanging fruit was a different advisor and a direct manual fix.

### Three harness bugs identified (not fixed)

1. **Dirty working tree after SKIPPED_PARSE_ERROR.** When `_parse_developer_output` returns `None`, the file is already written to disk but not reverted (revert logic only runs on SKIPPED_REVERT path). Manifested as iter 5 failing tests against iter 3's half-written `brick_packer.py` content. Workaround: `git checkout HEAD -- <file>` after the run.

2. **DEVELOPER_TIMEOUT_S too tight.** 300s too short for complex source files — developer agent hits the limit before producing valid JSON for large modules.

3. **JSON schema causes truncation.** Full file-content JSON schema (changes[].content) gets truncated for large source files, producing a SKIPPED_PARSE_ERROR instead of a usable diff.

### Manual improvement 1 — Replace `part_variety` with `color_match` advisor

`part_variety` replaced because the build is monochromatic yellow but the input cake image has multiple colors — a directly observable and fixable problem. New advisor reads `[preview_png, input_image]` and scores on dominant color accuracy, color count, and color family match vs. the input image.

Files changed:
- `tests/harness/advisors.yaml`: replaced `part_variety` advisor entry with `color_match`
- `tests/harness/run_harness.py`: `DIMENSION_SOURCE_FILES` updated (`color_match` → `color_service.py · suggestion_service.py`)
- `tests/harness/test_advisors.py`: `EXPECTED_IDS`, reads parametrize updated
- `tests/harness/test_developer_agent.py`: all 5 `part_variety` references updated to `color_match`

### Manual improvement 2 — `_apply_surface_tiles()` in brick_packer.py

Iter 3's developer agent drafted `_apply_surface_tiles()` with the right idea but couldn't land it (SKIPPED_PARSE_ERROR). Implemented properly with `TILE_PART_IDS` as a public constant in `brick.py` (single source of truth, per code-quality conventions).

Logic: scan all placements to find max Y per (x,z) stud, then replace any brick whose entire footprint sits at the top surface with the matching tile variant. Supported tile sizes: 1×1 (3070b), 1×2 (3069b), 1×3 (63864), 1×4 (2431), 2×2 (3068b), 2×4 (87079).

Files changed:
- `src/brickomancer/models/brick.py`: added `TILE_PART_IDS` dict
- `src/brickomancer/services/brick_packer.py`: added `_apply_surface_tiles()`, called after `connectivity_repair()` at end of `pack()`; updated import
- `tests/test_brick_packer.py`: `test_part_ids_valid` extended to accept `TILE_PART_IDS` values; import updated

Commit: 19b840a. 303 unit tests passing, 0 type errors, 0 lint violations.

---

## 12. Gold Dataset Integration + 8th Advisor (2026-06-13)

**311/311 tests passing. Zero type errors. Zero lint violations.**

### What was built

- **Gold dataset added** — `docs/example_input_output/star/`: `input_image/cartoon_star.jpg` (primary input), `input_image/cartoon_star2.png` (second variant), and 10 gold step PNGs (`step_output/star_step_01.png` … `star_step_10.png`) representing the ideal output for that subject.
- **Harness input switched** — `_INPUT_IMAGE_PATH` (single constant) replaced with `_INPUT_IMAGE_DIR` + `_pick_input_image()`, which randomly selects one image from the directory at the start of each iteration. Prevents overfitting to a single fixture.
- **`reference_fidelity` advisor** — 8th advisor in `advisors.yaml` that reads `[preview_png, gold_step_final]` and scores how closely the generated build matches the gold final-step image (`star_step_10.png`) on star silhouette, yellow coloring, scale, and surface flatness.
- **`input_image_path` threaded through** — `pipeline_executor` now accepts and returns the selected image path; `_run_single_advisor` reads it from `iteration_state` instead of a global; `scores.jsonl` records `input_image` per entry for full traceability.
- **Tests updated** — `test_advisors.py`, `test_advisor_engine.py` updated for 8 advisors; `test_pipeline_executor.py` updated for new signature and `input_image_path` return key. ThreadPoolExecutor bumped to `max_workers=8`.

### Files changed

| File | Change |
|---|---|
| `docs/example_input_output/star/` | New gold dataset directory (untracked → staged) |
| `tests/harness/advisors.yaml` | Added `reference_fidelity` advisor (8th) |
| `tests/harness/run_harness.py` | `_INPUT_IMAGE_DIR`, `GOLD_STEP_FINAL_PATH`, `_pick_input_image()`, pipeline_executor signature, `gold_step_final` reads handler, scores entry `input_image` field |
| `tests/harness/test_advisors.py` | Updated for 8 advisors, `reference_fidelity` in EXPECTED_IDS |
| `tests/harness/test_advisor_engine.py` | Updated call count and dict-length assertions for 8 |
| `tests/harness/test_pipeline_executor.py` | `_INPUT_IMAGE` constant, all call sites updated, `input_image_path` key assertion |
| `README.md` | Status line updated |
| `CLAUDE.md` | Current state updated (8/8 advisors, gold dataset, 311 tests) |

### Fresh context notes for section 12

| Issue | Detail |
|---|---|
| Adding more input images | Drop any `.jpg/.jpeg/.png/.webp` into `docs/example_input_output/star/input_image/` — `_pick_input_image()` auto-discovers them, no code change needed |
| Gold reference is fixed | `GOLD_STEP_FINAL_PATH` always points to `star_step_10.png` regardless of which input image was selected; both star inputs are expected to produce a star-shaped build |
| `reference_fidelity` source files | Maps to `image_pipeline.py` + `brick_packer.py` in `DIMENSION_SOURCE_FILES` — the shape generation layer is where star-shape fidelity improvements live |

---

## 13. Harness Calibration + Run 2 (2026-06-13)

**311/311 tests passing. Zero type errors. Zero lint violations.**

### What was built

- **`height_studs` pinned to 5** — replaced `_HEIGHT_STUDS_RANGE = (4, 6)` random range with `_HEIGHT_STUDS = 5` constant. Gold reference star build is ~5 bricks tall; randomizing height introduces scoring noise the developer agent cannot fix through code changes. Image randomization kept (2 inputs); height is deterministic.
- **Server restarts after each PASS_COMMITTED** — previously the server ran for the full N iterations with stale code; all iterations in a run were scoring the pre-run baseline. Now `_terminate_server` + `_start_server` + `_wait_for_server` run between iterations whenever a commit lands. Server log opened in append mode (`"ab"`) so restart logs are preserved.
- **`height_studs` parameter threaded through** — `pipeline_executor(iteration_dir, input_image_path, height_studs)` signature; returned in state dict; recorded in `scores.jsonl` as `height_studs` field.
- **PowerShell launch required** — `CLAUDE_CODE_OAUTH_TOKEN` is a Windows user-level env var that does not propagate to Bash subshells. First run attempted via Bash produced 3 `SKIPPED_NO_TOKEN` iterations before being aborted and relaunched via PowerShell with explicit `[System.Environment]::GetEnvironmentVariable(...)` load.

### Run 2 results (5 iterations, star gold dataset)

3 commits landed, 1 SKIPPED_REVERT, 1 SKIPPED_TIMEOUT.

| Commit | Dimension | Change |
|---|---|---|
| 8bd95b3 | shape_fidelity | Transpose voxel axes (0,2,1): star face (XY in TripoSR output) becomes XZ brick-layer footprint instead of tall column |
| 81fd8e2 | build_stability | Fix tile Y in `ldraw_writer._to_ldu`: tiles are 8 LDU tall, Y = `y*-24+16` not `y*-24` |
| bd1b576 | color_match | Add `_select_subject_color()` in suggestion_service: skips near-white/near-gray colors (sat ≤ 0.15, lightness ≥ 0.35) so yellow star body drives color extraction |

One SKIPPED_REVERT: `color_service.py` white-background filter broke `test_extract_colors_cake_dominant_colors` (test expects White in cake.jpg colors; filter removed it). The fix was attempted twice — dev agent needs to update the test alongside the change.

### Key insight: scores in a run reflect server-start-time code

Because the server doesn't hot-reload Python modules, all iterations in a run evaluate whatever code was committed *before* `_start_server`. The server-restart fix (above) changes this: from now on, each PASS_COMMITTED iteration's changes are live for the next iteration. The 3 commits from run 2 were first evaluated only in run 3+.

### Files changed

| File | Change |
|---|---|
| `tests/harness/run_harness.py` | `_HEIGHT_STUDS = 5` constant; `_pick_height_studs()` returns it; server restart block after PASS_COMMITTED; `_start_server` log append mode; `height_studs` in `_scores_entry` |
| `tests/harness/test_pipeline_executor.py` | All `pipeline_executor` calls updated to pass `height_studs=5`; key-set assertion includes `height_studs` |

### Fresh context notes for section 13

| Issue | Detail |
|---|---|
| Token not inherited by Bash | Always launch harness from PowerShell with explicit `$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN","User")` before starting |
| Server restart cost | Server restarts after each PASS_COMMITTED; 2D extrusion is fast (no GPU model load) so restarts are quick now |
| `test_extract_colors_cake_dominant_colors` blocker | Any change that filters white from color_service must also update this test. Dev agent needs explicit instruction to update the test alongside the fix |

---

## Session notes — 2026-06-14

### Run 3 results (5 iterations, star gold dataset)

1 commit landed, 2 SKIPPED_REVERT, 1 SKIPPED_TIMEOUT, 1 SKIPPED_REVERT.

| Iter | Commit | Dimension | Result | Change |
|---|---|---|---|---|
| 1 | — | shape_fidelity | SKIPPED_REVERT | `_apply_silhouette_mask()` — tests in test_image_pipeline.py expected TripoSR path; reverted |
| 2 | — | shape_fidelity | SKIPPED_TIMEOUT | Developer agent timed out on shape_fidelity change |
| 3 | ea0f2d0 | build_stability | PASS_COMMITTED | Masonry offset on odd layers: `x - bw//2` starting position before fallback to `x` |
| 4 | — | shape_fidelity | SKIPPED_REVERT | Full 2D extrusion bypass of TripoSR — 4 tests failed (test suite locked to TripoSR contract) |
| 5 | — | pdf_completeness | SKIPPED_REVERT | `0 STEP` after every batch including last — `test_no_trailing_step_marker` blocked it |

### Post-run 3 fix: replaced TripoSR with 2D silhouette extrusion

After run 3 confirmed the developer kept trying (and failing) to bypass TripoSR, the tests were manually updated and the feature was landed:

- **`image_pipeline._extrude_silhouette(rgba_image, height_studs)`**: extracts rembg alpha channel, resizes to `(height_studs × height_studs)` stud footprint, extrudes uniformly to produce `(X, height_studs, Z)` bool array. Produces star-shaped voxel grid instead of TripoSR rectangular blob.
- **`image_pipeline.run()`**: now calls `_remove_background()` → `_extrude_silhouette()` only. TripoSR functions remain in module for reference but are not called.
- **`test_image_pipeline.py`**: removed TripoSR-specific tests (`mock_triposr` fixture, `test_run_raises_import_error_when_triposr_unavailable`, `test_run_raises_value_error_when_trimesh_load_returns_scene`); added `test_extrude_silhouette_*` tests; updated `run()` tests to use RGBA mocks. Net: 311 → 313 passing.

Commit: `96ffeb8`

### Files changed (run 3 + post-run fix)

| File | Change |
|---|---|
| `src/brickomancer/services/brick_packer.py` | Masonry offset on odd layers (ea0f2d0) |
| `src/brickomancer/services/image_pipeline.py` | Add `_extrude_silhouette()`; `run()` now uses rembg → silhouette extrusion; removed TripoSR call; removed `import tempfile` (96ffeb8) |
| `tests/test_image_pipeline.py` | Remove TripoSR-specific tests; add `_extrude_silhouette` unit tests; update `run()` tests to RGBA mocks (96ffeb8) |

---

## Session notes — 2026-06-14 (run 4)

### Run 4 results (5 iterations, star gold dataset)

1 commit landed, 1 SKIPPED_TIMEOUT, 1 SKIPPED_PARSE_ERROR, 2 SKIPPED_REVERT.

| Iter | Commit | Dimension | Result | Change |
|---|---|---|---|---|
| 1 | — | reference_fidelity | SKIPPED_TIMEOUT | Developer agent timed out (300s limit) |
| 2 | — | aesthetics | SKIPPED_PARSE_ERROR | Developer agent output unparseable |
| 3 | — | pdf_completeness | SKIPPED_REVERT | LPub3D meta-commands (cover page + BOM + trailing STEP) — broke 3 step-marker tests |
| 4 | 6d67628 | instruction_clarity | PASS_COMMITTED | Y-layer-first step sequencing: `sequence_steps` groups by voxel Y-layer so each layer is a distinct build step |
| 5 | — | build_stability | SKIPPED_TIMEOUT | Developer agent timed out (300s limit) |

### Post-run 4 manual fixes

Two issues observed across run 3 and run 4 were fixed manually and committed as `acf8ca6`:

**Trailing `0 STEP` contract (`acf8ca6`):** `write_ldr` now emits `0 STEP` after every step including the last, so LPub3D generates a separate page per build step. Three unit tests updated to match new contract (`test_no_trailing_step_marker` → `test_trailing_step_marker_present`; step counts corrected). Developer agent had tried this 3 times across runs 3–4 and been blocked by the old test assertions each time.

**Developer timeout raised 300→600s (`acf8ca6`):** Two iterations timed out at 300s in run 4. Timeout raised to 600s to reduce SKIPPED_TIMEOUT rate for complex dimensions (reference_fidelity, build_stability).

**LDView camera angles (folded into repo-update commit):** `-Latitude=30 -Longitude=45` added to `subprocess_utils.run_ldview` args for better 3D perspective in preview PNGs. Improves aesthetics advisor scoring.

### Files changed (run 4 + post-run fixes)

| File | Change |
|---|---|
| `src/brickomancer/services/ldraw_writer.py` | Y-layer-first step sequencing in `sequence_steps`; trailing `0 STEP` after every step (6d67628, acf8ca6) |
| `src/brickomancer/utils/subprocess_utils.py` | LDView camera preset: `-Latitude=30 -Longitude=45` |
| `tests/test_brick_packer.py` | Updated 3 step-marker tests to expect trailing STEP; renamed `test_no_trailing_step_marker` → `test_trailing_step_marker_present` (acf8ca6) |
| `tests/harness/run_harness.py` | `DEVELOPER_TIMEOUT_S` 300→600 (acf8ca6) |

### Fresh context notes for run 4

| Issue | Detail |
|---|---|
| Step-marker test wall resolved | `test_trailing_step_marker_present` (was `test_no_trailing_step_marker`) now expects `count == 1`; dev agent can freely add trailing STEPs |
| Developer timeout | Now 600s — timeouts should be rare; if still hitting them, check advisor prompt complexity for that dimension |
| Recurring pdf_completeness target | Dev agent keeps adding LPub3D meta-commands (cover page, BOM); these may now pass tests since trailing STEP is allowed |
| Run 2 scores low overall | avg_raw ~2.5–3.1 across 8 dims; shape_fidelity and reference_fidelity stuck at 1. Root cause: TripoSR reconstructs flat cartoon star as a blob, not a 5-pointed shape. Axis transpose helps orientation but not reconstruction quality. Scores will improve as run 2 commits are evaluated in future runs. |

---

## Harness run 5 (2026-06-14)

**Summary:** 5 iterations, avg raw 3.4 → 4.0 at close. Runs 3 and 5 SKIPPED_REVERT — developer agent proposed axis changes (Y→Z) which 3 correct tests blocked. Root causes identified in INV-7: (1) rembg server-side ~3 True voxels/layer vs 117 locally; (2) stride-2 downsample loses star arms on odd indices; (3) no integration test for degenerate output.

| Iter | SHA | Dimension | Result | Notes |
|---|---|---|---|---|
| 1 | 0818782 | build_stability | PASS_COMMITTED | Minimum 2×2 stud footprint padding before packing |
| 2 | 8fb28aa | shape_fidelity | PASS_COMMITTED | Pre-binarize alpha at full resolution before downsampling |
| 3 | — | shape_fidelity | SKIPPED_REVERT | Axis change (Y→Z extrusion) blocked by 3 tests |
| 4 | bdb2d7e | shape_fidelity | PASS_COMMITTED | α-threshold 128→32 to include attenuated star tips |
| 5 | — | reference_fidelity | SKIPPED_REVERT | Axis change blocked again |

### Post-run 5 shape-quality plan (#32, 2026-06-13/14)

Root-cause fixes landed as a `/build-phase` run on `docs/shape-quality-plan.md` (Steps 1, 4, 5, 6; Steps 2/3 deferred/conditional):

| Step | SHA | What |
|---|---|---|
| Pre-flight | b1aae9b | ruff I001 fix in ldraw_writer.py imports |
| Step 1 | (merged) | Sparse-fill guard + rembg diagnostic logging in image_pipeline.py; new test `test_extrude_silhouette_sparse_falls_back_to_solid` (315 tests) |
| Step 4 | (merged) | 2×2 OR-pool downsample in suggestion_service._downsample; new test `test_compact_downsample_preserves_star_shape` |
| Step 5 | (merged) | Integration test `tests/integration/test_star_pipeline.py` (gated on BRICKOMANCER_INTEGRATION=1) |
| Step 6 | (merged) | Axis-convention guard appended to developer-agent prompt in run_harness.py |

Step 2 (operator M1 — diagnose rembg fill% on live server) deferred. Step 3 (birefnet-general model switch) conditional on SPARSE verdict in `docs/investigations/INV-7-step2-verdict`.

---

## Harness run 6 (2026-06-14)

**Summary:** 5 iterations, avg raw 4.0 → 4.75. 4 committed, 1 SKIPPED_REVERT. No axis-change attempts (axis-convention guard worked). Developer agent targeted LDraw meta-commands and brick_packer orientation logic.

| Iter | SHA | Dimension | Result | Notes |
|---|---|---|---|---|
| 1 | d4405b0 | pdf_completeness | PASS_COMMITTED | Added `0 !LPUB INSERT BOM` meta command (BOM page) |
| 2 | 6d6f8a2 | pdf_completeness | PASS_COMMITTED | Moved BOM command after final `0 STEP` (valid page boundary) |
| 3 | 15b8f0a | instruction_clarity | PASS_COMMITTED | Added `0 !LPUB FADE STEPS ENABLED` header (previously-placed bricks faded) |
| 4 | — | instruction_clarity | SKIPPED_REVERT | ROTSTEP+STEP hero-angle final page broke 3 step-marker tests |
| 5 | 7d202dc | build_stability | PASS_COMMITTED | Alternating brick orientation on odd layers (cross-bond interlocking) |

### Files changed (run 6)

| File | Change |
|---|---|
| `src/brickomancer/services/ldraw_writer.py` | BOM insert + position fix + FADE STEPS header (d4405b0, 6d6f8a2, 15b8f0a) |
| `src/brickomancer/services/brick_packer.py` | Alternating orientation on odd layers (7d202dc) |

### Fresh context notes for run 6

| Issue | Detail |
|---|---|
| ROTSTEP hero-page blocked | Appending ROTSTEP+STEP after build steps breaks `test_step_markers_every_8`, `test_trailing_step_marker_present`, `test_step_marker_after_exactly_8`. These tests are intentional — update them if pursuing hero page. |
| shape_fidelity still at 3 | Root cause is rembg sparsity (M1 UAT pending). Sparse-fill guard prevents 1×1 column but doesn't fix the star shape. birefnet-general model (Step 3) would help most. |
| build_stability at 2 | Cross-bond fix (7d202dc) didn't move the score. Advisors may want true masonry interlocking across layers, not just within-layer alternation. |
| build_stability still at 2 | Cross-bond alternating orientation committed (7d202dc) but score unchanged. Advisors likely want true interlocking across layer boundaries, not same-layer orientation variety. |

---

## Harness run 7 (2026-06-14)

**Summary:** 5 iterations, avg raw 3.125→3.875. 3 committed, 2 reverted. Key finding: `!LPUB FADE STEPS ENABLED` committed in run 6 iter 3 was malformed (missing TRUE/FALSE arg), causing LPub3D to blank every PDF page — root cause of 0 scores for instruction_clarity and pdf_completeness throughout this run. Fixed in iter 4. pdf_completeness still 0 and instruction_clarity still 1 in iter 5 (post-fix), suggesting additional PDF quality issues remain.

| Iter | SHA | Dimension | Result | Notes |
|---|---|---|---|---|
| 1 | — | shape_fidelity | SKIPPED_REVERT | birefnet-general model switch broke `test_remove_background_returns_rgba_image` |
| 2 | — | reference_fidelity | SKIPPED_REVERT | OR-pool resize change broke `test_extrude_silhouette_rgb_input_treated_as_opaque` |
| 3 | 2c05feb | technical_validity | PASS_COMMITTED | Tile decomposition: non-standard bricks (e.g. 2×3) split into 1-wide tile strips |
| 4 | 90efe32 | pdf_completeness | PASS_COMMITTED | Removed malformed `!LPUB FADE STEPS ENABLED` (blanked every PDF page) |
| 5 | 0533e5e | aesthetics | PASS_COMMITTED | LDView camera latitude 30°→45°, resolution 800×600 |

### Harness output restructure (this session)

Flat output directory: `iteration_N/` subdirectories removed. All per-iteration files now written directly to `tests/harness/runs/` with prefix `i{n}_{HHmm}_` (e.g. `i1_1435_instructions.pdf`). Tests updated accordingly.

### Files changed (run 7 + restructure)

| File | Change |
|---|---|
| `src/brickomancer/services/ldraw_writer.py` | Tile decomposition for non-standard brick sizes (2c05feb); malformed FADE header removed (90efe32) |
| `src/brickomancer/utils/subprocess_utils.py` | LDView camera latitude 30°→45°, 800×600 resolution (0533e5e) |
| `tests/harness/run_harness.py` | Flat output dir: `pipeline_executor` and `advisor_engine` take `(runs_dir, file_prefix, ...)` instead of `iteration_dir`; main loop computes `i{n}_{HHmm}` prefix |
| `tests/harness/test_pipeline_executor.py` | Updated all calls for new signature + filename assertions |
| `tests/harness/test_advisor_engine.py` | Updated integration test calls for new signature |

### Fresh context notes for run 7

| Issue | Detail |
|---|---|
| FADE STEPS header history | Run 6 iter 3 added `0 !LPUB FADE STEPS ENABLED` (no TRUE/FALSE). Run 7 iter 4 removed it. Do NOT re-add without `TRUE` argument: `0 !LPUB FADE STEPS ENABLED TRUE`. |
| pdf_completeness still 0 post-fix | Even after removing malformed FADE header, iter 5 scored pdf_completeness: 0 and instruction_clarity: 1. PDF is 1186 bytes — consistent with previous runs. Root cause unclear; advisors may have strict page-content requirements. |
| birefnet model test break | Dev agent tried birefnet-general switch (iter 1) but `test_remove_background_returns_rgba_image` failed. Test expects RGBA output; birefnet integration changed the return type. If retrying, fix the test alongside the implementation. |
| Flat output naming | Files: `i{n}_{HHmm}_instructions.pdf`, `i{n}_{HHmm}_preview.png`, `i{n}_{HHmm}_advisor_reports.json` — all in `tests/harness/runs/`. |

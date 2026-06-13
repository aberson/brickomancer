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
- `uv run pytest -q` — run as quality gate after each developer agent change.
  182 passing tests must stay passing.

**End-to-end verification:**

Step 17 (smoke gate) is the primary integration test for the harness itself. It verifies
the full loop works with real TripoSR inference, real LPub3D PDF generation, and real
advisor scoring. This is deliberately an operator step — the harness cannot test itself
automatically without running the full 30–60s TripoSR pipeline.

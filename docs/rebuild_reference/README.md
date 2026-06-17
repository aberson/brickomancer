# Rebuild reference — archived v1 harness artifacts

Archived 2026-06-17 during Phase 1 Step 1 (rebuild). The old v1 hill-climbing harness
(`tests/harness/`) was removed; **Step 9 rebuilds it from scratch** with a render-scoring
regression gate. These four files are preserved here as design reference for that rebuild.

| File | What it is | Why kept |
|---|---|---|
| `advisors.yaml` | The v1 9-dimension scoring rubric (shape_fidelity, reference_fidelity, build_stability, pdf_completeness, instruction_clarity, color_match, technical_validity, aesthetics, warnings_judge). | The dimension definitions + scoring guidance are the starting point for Step 9's judge. |
| `judge.py` | The v1 judge: `DIMENSION_SOURCE_FILES` map + the structured change-brief prompt. | Step 9's judge reuses the prompt shape; the dimension→file mapping informs the new judge. |
| `applier.py` | The v1 applier: Claude-subprocess apply → pytest gate → commit-or-revert loop. | Step 9 replaces the pytest-only gate with a render-score regression gate; this is the baseline to diff against. |
| `scores.jsonl` | 160 iterations of v1 optimization history (per-iteration per-dimension scores). | **This was `.gitignore`d in v1 — this archive is its ONLY copy.** Evidence of the plateau (avg sat in the 3.5–5.1 band); useful for calibrating Step 10. Analyzed in [`../investigations/rebuild/02-plateau-postmortem.md`](../investigations/rebuild/02-plateau-postmortem.md). |

The full old harness (run_harness.py, pipeline.py, advisor.py, server.py, and the harness
test files) is recoverable from git history at commit `9d6091f` (path `tests/harness/`).
Only `scores.jsonl` and `runs/` were gitignored, so only `scores.jsonl` needed archiving
to survive the deletion.

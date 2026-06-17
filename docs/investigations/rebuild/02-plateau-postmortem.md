# Plateau Post-Mortem — Why the Harness Stalled at ~5/10

Root-cause diagnosis from primary sources: `tests/harness/scores.jsonl` (160 rows),
`tests/harness/runs/*_advisor_reports.json`, the harness source, and the rendered preview PNGs.

## The two ceilings

Effort produced motion but not progress because **two distinct ceilings were active at once**.

### Ceiling A — representation (architectural)

The image path fabricates depth instead of recovering it. `_extrude_silhouette`
([image_pipeline.py:223-230](../../../src/brickomancer/services/image_pipeline.py#L223-L230))
builds a **radial-dome height map** — tallest at the centroid, shortest at the edges. A star's
points live at the edges → shortest columns → they vanish. Advisors said this iteration after
iteration:

> "a staircase-like zigzag column with no radiating arms" (iter ~i20_0233)
> "stacked rectangular/L-shaped mass with no arm-like protrusions… pointed tips entirely absent" (i20_1141)
> "only 4 protrusions… lacks the concave indentations" (i20_1454, the *best* case)

`shape_fidelity` was stuck at 2–4 the entire run; `reference_fidelity` capped at 3–4. The gold
reference is a sculptural 3D star *character* with a printed face — information that is simply
not in a 2D silhouette and not derivable by any heuristic. The harness could only edit single
files inside the existing pipeline ([judge.py](../../../tests/harness/judge.py)
`DIMENSION_SOURCE_FILES`), so it could never escape this ceiling.

### Ceiling B — feedback loop (process)

The commit gate is **pytest only** ([applier.py:172-231](../../../tests/harness/applier.py#L172-L231)):
write file → run pytest → commit if green, revert if red. **The output is never re-rendered or
re-scored before committing.** So the loop optimizes "passes unit tests," not "raises the score."

Measured consequences from `scores.jsonl`:

| Outcome | Count (of 160) |
|---|---|
| PASS_COMMITTED | 81 |
| SKIPPED_REVERT | 41 |
| SKIPPED_JUDGE_FAILED | 11 |
| SKIPPED_NO_TOKEN | 10 |
| SKIPPED_TIMEOUT | 9 |
| SKIPPED_PARSE_ERROR | 7 |
| PASS_COMMIT_FAILED | 1 |

- **`pdf_completeness` and `instruction_clarity` sat at 0 for ~40 committed iterations**
  (iters ~50–114). A broken LPub3D meta config passes pytest (which renders no PDF), so the
  damage persisted unseen and uncorrected.
- **~30 commits of meta-command whack-a-mole**: FADE_STEPS / HIGHLIGHT_STEP / COVER_PAGE / BOM
  added → removed → re-added → reordered. `warnings_judge` even *detected* the oscillation
  ("FADE_STEPS lines added iter 14 then removed iter 15 — loop toggled the identical feature")
  and still couldn't stop it, because the actual rendered effect was never measured by the gate.
- **`avg_raw` never trended up** — it stayed in the 3.5–5.1 band across the whole run. The
  quality gate (`avg_raw >= 8.0`) was never approached.

> **Note on `avg_normalized` = 5.0:** `advisor._normalize_scores` z-scores the per-iteration
> advisor scores and re-centers the mean to 5.0, so the per-iteration normalized average is
> ~5.0 *by construction*. The "plateau at 5" in that column is a math artifact. The real signal
> is `avg_raw`.

## Per-dimension classification

**(a) Fixable with better code in the same architecture**
- `pdf_completeness` / `instruction_clarity` — pure LPub3D meta syntax + ordering. A
  known-good config demonstrably exists (it recovered to 4–5 by iter ~141). The problem was the
  loop's inability to *lock in* a good config, not difficulty. → Freeze the meta header.
- `color_match` — strongest dimension (7–8). Subject masking + Lab cache works.
- `technical_validity` — 6–9; residual issues are part-count/BOM bookkeeping bugs.

**(b) Fixable only with a different technical approach**
- `shape_fidelity` — capped by Ceiling A. Needs a true 3D shape source.
- `build_stability` — stuck at 2–5 despite the *most* attempts. Greedy-place-then-patch can't
  guarantee soundness; advisors kept finding "1×1 bricks directly column-stacked",
  "three-layer column stack with no horizontal offset". Needs a packer with support/connectivity
  as a hard constraint.

**(c) Inherently hard for this target**
- `reference_fidelity` — matching an artist's interpretive 3D figurine (with a face) from a 2D
  cartoon silhouette. Either change the representation or change the reference target.
- `aesthetics` — downstream of shape + stability; can't lead them.

## The fix (carried into the rebuild)

1. **Replace the representation** (Ceiling A) — true single-image-to-3D model. See
   [03-better-approaches.md](03-better-approaches.md) §1.
2. **Replace the packer** — connectivity-graph structural model. See §2.
3. **Close the loop** (Ceiling B) — the missing rung is **re-render + re-score + regression-gate
   on the score** between pytest and commit. A change merges only if the targeted dimension does
   not regress below its committed baseline and avg does not drop. See §4.
4. **Pin the fragile surface** — the LPub3D meta header becomes a constant in
   `constraints_to_preserve` that the judge is forbidden to edit, removing the oscillation surface.

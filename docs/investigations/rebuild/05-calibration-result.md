# 05 — Phase 4 Step 10 Calibration Result

**Date:** 2026-07-15
**Step:** Phase 4, Step 10 (#59) — calibration run (`Type: wait`)
**Branch:** `calibration/step10` (isolated so any source-mutating commits stay off master)
**Run:** `uv run python -m tests.harness.loop --iterations 3` (text eval set — no GPU)

## Verdict

The rebuilt harness ran **end-to-end without crashing** and logged a complete trajectory to
`tests/harness/scores.jsonl`. The score trajectory is **flat** (`avg_raw 8.25 → 8.25`, **0
committed**). Per the plan, a flat trajectory is an explicitly valid, ship-worthy finding —
and this run pins the *cause* precisely, which is the real value.

## Trajectory (from `scores.jsonl`)

| iter | selected dim | result | avg_raw |
|---|---|---|---|
| 0 (baseline) | — | BASELINE | **8.25** (pdf 10.0, tech 10.0, **build_stability 3.0**, part_variety 10.0) |
| 1 | build_stability | `SKIPPED_DEV` | — |
| 2 | build_stability | `SKIPPED_JUDGE` | — |
| 3 | build_stability | `SKIPPED_DEV` | — |

- **No dimension hit 0.** `build_stability = 3.0` is the low one (real headroom).
- **No oscillation** — nothing was committed or reverted, so there was nothing to oscillate.
- **The gate never had to fire**: no change reached it (every iteration skipped upstream).

## Root cause of the flat trajectory (this is the finding)

It is **not** scorer saturation (my going-in hypothesis was wrong): `build_stability = 3.0`
has clear headroom. It is **not** judge failure either. It is the **developer step**.

1. **The judge works, and reasons about the REAL code.** A diagnostic call returned a
   valid decision after a prose preamble (the brace-scan extracts it — `_parse_decision`
   returns a decision). It correctly picked `build_stability` over the maxed `part_variety`
   and grounded it in the actual packer: *"residual fragility that survives the contract —
   articulation points (single-bond fragments) and single-stud grips, which
   `_eliminate_arm_tip_articulations` only partially removes."* The intelligence is there.
   (Iter 2's `SKIPPED_JUDGE` is the judge's occasional miss — output without a clean JSON
   object; the parser should strip markdown fences to reduce it.)
2. **The developer step is the systematic bottleneck (`SKIPPED_DEV`, iters 1 & 3).** It asks
   `claude -p` to emit the **entire new source file** as a single-line JSON-escaped
   `{"content": "..."}` string. For a ~1000-line file like `brick_packer.py`, claude returns
   prose + a fenced code block, not a strict JSON blob — so `_parse_content` returns None and
   the iteration skips. The whole-file JSON round-trip does not scale to real source files.

So the hill-climb never applied a single change: the judge chose a sound lever every time, but
the developer step could not deliver an applyable edit.

## Secondary finding — build_stability = 3.0 is a real quality signal

The text-shaped builds (star / dog / chair / heart) score `build_stability = 3.0`, meaning the
packer produced **>1 connected component OR unsupported bricks** for them (the scorer gives
10.0 only for 1 component ∧ 0 unsupported). The connectivity *contract* holds for the packer's
own fixtures (cube/star grids), but text-emitted grids expose residual fragility. That is
genuine packer headroom a working hill-climb would target.

## Actionable follow-ups (NOT required for Step 10's done-when)

1. **Fix the developer step (highest leverage).** Stop round-tripping whole files through JSON.
   Options: (a) have the developer emit a unified diff / search-replace block and apply it, or
   (b) drive the edit through a file-writing tool call rather than a `content` string. This is
   what unblocks a real climb.
2. **Harden the judge parse** — strip ```` ```json ```` fences before the brace-scan to kill the
   occasional `SKIPPED_JUDGE`.
3. **Richer scorer dimensions** — 3 of 4 dims are already maxed; add the LLM-judged rendered
   dimensions (shape_fidelity, aesthetics, instruction_clarity) so there is more to climb once
   the developer step lands changes.

## What Step 10 delivered

- The full loop (`judge → developer → render-score gate`), dry-tested (`test_loop.py`) and run
  live end-to-end; `scores.jsonl` incremental logging; CLI entry point.
- The calibration **completed and was observed** — the plan's `Type: wait` done-when. The
  observation is that the mechanism is sound but the developer step needs the diff-based rewrite
  above before the loop can actually hill-climb.
- **Zero source mutated** (0 committed), so nothing risky landed; the branch carries only the
  loop code + this note.

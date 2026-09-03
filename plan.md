# Brickomancer - Plan Index

The canonical plan of record has moved to
[`documentation/rebuild-plan.md`](documentation/rebuild-plan.md)
(the full rebuild - Steps 0.1-10, all DONE at commit 15f72e6, 2026-07-15).

Superseded v1 documents, left in place, each carrying its own superseded-by
header (plain paths below, deliberately NOT links):

- `docs/master_plan.md` - v1 architecture; still the live reference for the
  API contract, LDraw appendix and 28-color safe palette.
- `docs/shape-quality-plan.md` - v1 shape quality; its Step 4 (2x2 OR-pool
  downsample) is still cited by rebuild-plan Step 7.
- `docs/harness-plan.md` - v1 harness plan plus its run-by-run log.

## Why this file is a pointer stub (do not delete it)

dev-observatory's `plan_locate.find_plan` searches the repo root before
`docs/` and prefers the canonical filenames `plan.md` / `master_plan.md`.
Without this stub it lands on `docs/master_plan.md` and reports v1 state on
the dashboard. `plan_locate._follow_redirect` resolves this file one hop to
the real plan, so two properties are load-bearing:

1. Keep it under 30 non-blank lines (`_STUB_MAX_NONBLANK_LINES`).
2. Keep exactly one markdown link to a `.md` file, pointing at the rebuild
   plan. A second link naming `plan.md` or `master_plan.md` would win the
   canonical-name preference and send the finder back to the v1 plan.

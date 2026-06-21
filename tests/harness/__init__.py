"""Rebuilt quality harness (Phase 4, Step 9).

The v1 harness was removed in Phase 1 (archived under docs/rebuild_reference/). This
rebuild's defining change: the commit gate is **rendered-output score regression**, not
pytest alone. The v1 plateau (02-plateau-postmortem) traced ~30 commits of meta-command
oscillation to a pytest-only gate that never re-rendered — the loop optimized "passes
unit tests," not "raises the score".

Modules:
  - ``judge``   — dimension→source-file map + ``CONSTRAINTS_TO_PRESERVE`` (the frozen
    invariants the judge may never edit, incl. the BOM-only LPub3D header) + the
    change-brief prompt builder.
  - ``scorer``  — ``EVAL_SET`` + ``render_and_score`` (re-render + re-score the eval set).
  - ``applier`` — the gate: apply → pytest → **re-render + re-score** → commit only if no
    score regression, else revert. ``run_tests`` and ``render_and_score`` are injectable so
    the regression-gate test drives it deterministically (no slow real render in the gate).

The full unattended hill-climb loop runs in Step 10 (calibration); Step 9 ships and tests
the regression gate that makes that loop trustworthy.
"""

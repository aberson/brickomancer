# Task State — Brickomancer

**Task:** Run harness 20 iterations (run-10)
**Status:** READY — waiting for new session to launch
**Last written:** 2026-06-15T00:00:00Z
**Session SHA:** 088730b

## Current WIP

Harness refactor complete (judge+applier architecture, warnings_judge as 9th advisor, 340 tests). Committed and pushed as 088730b (issue #45 closed). Ready to run harness run-10.

## Next Action

Run the harness 20 iterations from PowerShell (NOT Bash tool — Bash doesn't inherit Windows user env vars):

```powershell
$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")
$env:PATH += ";C:\Tools\LPub3D"
uv run python tests/harness/run_harness.py --iterations 20
```

Then review `tests/harness/scores.jsonl` and the most recent `tests/harness/runs/*_advisor_reports.json` to report results.

## Completed This Session

- Harness refactored: `run_harness.py` split into `pipeline.py`, `advisor.py`, `server.py`, `judge.py`, `applier.py`
- `developer.py` deleted; stochastic hill-climbing replaced with judge+applier loop
- `warnings_judge` added as 9th advisor (reads scores_history, detects oscillation/revert storms)
- `test_judge.py` (13 tests) + `test_applier.py` (10 tests) added
- 340 tests passing, 0 type errors, 0 lint violations
- README, CLAUDE.md, master_plan.md updated; memory updated
- Committed 088730b, issue #45 created+closed, pushed to master

## Key Files

- `tests/harness/run_harness.py` — thin entry point
- `tests/harness/judge.py` — reads advisor reports, produces change brief
- `tests/harness/applier.py` — executes change brief, commits or reverts
- `tests/harness/advisor.py` — 9 advisor engine including warnings_judge
- `tests/harness/scores.jsonl` — iteration history (used by warnings_judge)
- `tests/harness/advisors.yaml` — 9 advisors including warnings_judge

## Critical Gotchas

- Always launch harness from PowerShell — Bash tool does NOT inherit Windows user env vars
- Load CLAUDE_CODE_OAUTH_TOKEN explicitly before running (see Next Action above)
- Set PATH to include LPub3D before starting
- Harness server runs on port 8005 (not 8000)
- pytest gate: `uv run pytest -q --ignore=tests/integration`
- Judge `blocking_issues` non-empty → applier returns SKIPPED_BLOCKED (no change made)
- warnings_judge score: 10=healthy, 0=crisis

## Pre-run-10 Dim Scores (run-9 end state)

- pdf_completeness: 0 (LPub3D meta commands removed by run-9 oscillation — judge should fix)
- instruction_clarity: 1
- build_stability: 2 (1×1 pillars at star arm tips)
- shape_fidelity: 3 (root cause fixed in 689f776 — expect improvement)
- reference_fidelity: 4; aesthetics: 5–6; color_match: 7; technical_validity: 5–9

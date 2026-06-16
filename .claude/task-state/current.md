# Task State — Brickomancer

**Task:** Fix harness issues then run_harness 20 iterations (run-11)
**Status:** IN_PROGRESS — run-10 complete with old code; fixes needed before run-11
**Last written:** 2026-06-15T20:00:00Z
**Session SHA:** b0c6825

## Current WIP

Run-10 completed 20/20 iterations but ran the **old pre-refactor code**, not judge+applier.
Evidence: `SKIPPED_PARSE_ERROR` in scores (old error code), log says "running 8 advisors",
log says "developer_agent: committed" instead of applier commit messages, no `judge_rationale`
field in scores.jsonl rows. Root cause: background process launched with `PYTHONPATH` trick
picked up stale `.pyc` bytecache or old import path — the new `run_harness.py` was never
actually executed.

Run-10 avg_raw scores: 3.25–5.375, no meaningful improvement over run-9 baseline (~3.375).
19 commits landed (iters 1–13, 15–16, 19 committed; 14, 18, 20 reverted).

## Issues to Fix Before Run-11

### Issue 1: Harness ran old code (CRITICAL)
The judge+applier loop never executed. `applier.py` log strings still say `developer_agent:`
(inherited from old code) — these need renaming so future runs are diagnosable.

**Fix:**
- In `applier.py`: rename all `log.info("developer_agent: ...")` calls to `log.info("applier: ...")`
- In `advisor.py`: fix log string "running 8 advisors in parallel" → "running %d advisors in parallel" with actual count
- Verify `run_harness.py` imports resolve correctly by running dry-run: `uv run python -c "from tests.harness.run_harness import main; print('OK')"` with PYTHONPATH set
- Delete `tests/harness/**/__pycache__` before next run to prevent stale .pyc interference
- Add `PYTHONIOENCODING=utf-8` to server launch command or set in environment to prevent cp1252 `→` crash

### Issue 2: server.py `→` arrow cp1252 crash (already fixed in this session)
`log.info("Server process started (pid=%d); log → %s")` crashes on cp1252 terminals.
Fixed: replaced `→` with `->` in server.py. Verify this is committed.

### Issue 3: warnings_judge not running (9 vs 8)
Log says "running 8 advisors in parallel" — `warnings_judge` not being invoked.
Check `advisor.py` thread pool size and whether `warnings_judge` is included in the
advisor list loaded from advisors.yaml.

### Issue 4: PYTHONPATH must be set for harness launch
Old invocation `uv run python tests/harness/run_harness.py` fails with
`ModuleNotFoundError: No module named 'tests'` unless `PYTHONPATH` is set.
The correct launch command is:
```powershell
$env:CLAUDE_CODE_OAUTH_TOKEN = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")
$env:PATH += ";C:\Tools\LPub3D"
$env:PYTHONPATH = "C:\Users\abero\dev\brickomancer"
$env:PYTHONIOENCODING = "utf-8"
uv run python tests/harness/run_harness.py --iterations 20
```

## Next Action

1. Check whether server.py `->` fix is committed (should be in working tree, not committed yet)
2. Fix applier.py log strings: `developer_agent:` → `applier:` 
3. Fix advisor.py log string: hardcoded "8" → actual count
4. Clear pycache: `Remove-Item -Recurse -Force tests/harness/__pycache__` (and src pycache)
5. Run dry-run import test to confirm new code loads: `$env:PYTHONPATH = "C:\Users\abero\dev\brickomancer"; uv run python -c "from tests.harness.run_harness import main; print('imports OK')"`
6. Commit fixes
7. Launch run-11: `$env:PYTHONPATH = "C:\Users\abero\dev\brickomancer"; $env:PYTHONIOENCODING = "utf-8"; uv run python tests/harness/run_harness.py --iterations 20`
8. Confirm iter 1 log shows "applier:" and "running 9 advisors" before leaving it to run

## Completed This Session

- Harness refactored: judge+applier architecture, warnings_judge (9th advisor), 340 tests (088730b)
- repo-update: README, CLAUDE.md, master_plan.md updated; issue #45 closed; pushed
- Run-10 launched and completed 20/20 iterations (ran old code — see issues above)
- server.py: `→` replaced with `->` to fix cp1252 crash (not yet committed)

## Dead Ends

- Running harness via background PowerShell task without PYTHONPATH → `ModuleNotFoundError: No module named 'tests'`
- Using `uv run python -m tests.harness.run_harness` as alternative (not tried yet — may work without PYTHONPATH)

## Key Files

- `tests/harness/run_harness.py` — thin entry point (judge+applier loop)
- `tests/harness/judge.py` — reads advisor reports, produces change brief
- `tests/harness/applier.py` — executes change brief; log strings say "developer_agent:" (BUG — fix)
- `tests/harness/advisor.py` — 9 advisor engine; log string says "8 advisors" (BUG — fix)
- `tests/harness/server.py` — server lifecycle; `->` fix applied, not committed
- `tests/harness/scores.jsonl` — run-10 results (20 rows, old code path)
- `tests/harness/advisors.yaml` — 9 advisors including warnings_judge

## Critical Gotchas

- Always launch harness from PowerShell — Bash tool does NOT inherit Windows user env vars
- PYTHONPATH must be set: `$env:PYTHONPATH = "C:\Users\abero\dev\brickomancer"`
- PYTHONIOENCODING must be utf-8 to prevent cp1252 crash on `→` or similar Unicode
- Set PATH to include LPub3D before starting
- Harness server runs on port 8005 (not 8000)
- pytest gate: `uv run pytest -q --ignore=tests/integration`
- Judge `blocking_issues` non-empty → applier returns SKIPPED_BLOCKED
- warnings_judge score: 10=healthy, 0=crisis
- Confirm run is using NEW code by checking first iter log for "applier:" and "9 advisors"

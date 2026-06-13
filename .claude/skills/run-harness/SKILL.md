---
name: run-harness
description: Prep, launch, and monitor the Brickomancer quality hill-climbing harness. Shows a full run-config panel, waits for "go", launches the script in the background, and posts status updates at 30s / 1m / 2m / 5m / then every 10m. Responds to "what's the status" at any time.
user-invocable: true
---

# run-harness

Invoke as `/run-harness [--iterations N]` (default N=5).

---

## Phase 1 — Pre-flight (silent; hard-stop on failure)

Run all checks before displaying anything.

1. **Token** — confirm `CLAUDE_CODE_OAUTH_TOKEN` is set as a Windows user env var:
   ```powershell
   $tok = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN","User")
   ```
   Hard-stop if missing: "CLAUDE_CODE_OAUTH_TOKEN not set — set it as a Windows user env var then re-run."

2. **Pytest baseline** — run `uv run pytest -q --ignore=tests/integration` from `c:\Users\abero\dev\brickomancer`.
   Hard-stop if non-zero: show the failure summary and say "Fix failing tests before running the harness."

3. **Port 8005** — check `Get-NetTCPConnection -LocalPort 8005 -ErrorAction SilentlyContinue`.
   If occupied: report PID and ask "Port 8005 is held by PID X. Kill it before launching? (y/n)"
   Wait for user answer before proceeding.

4. **Orphaned server on port 8000** — check same way. If occupied by a dead parent (process not in tasklist): report "Orphaned server on port 8000 (PID X) — informational only, will not interfere."

5. **Baseline scores** — read last 2 rows of `tests/harness/scores.jsonl`. Compute per-dimension trend (▲ / → / ▼) by comparing `scores_raw` between the two rows. If fewer than 2 rows exist, show → for all dimensions.

6. **Latest previous PDF** — check `tests/harness/runs/` for the highest-numbered `iteration_N/instructions.pdf`. Record the path for the panel.

---

## Phase 2 — Pre-flight panel

Display this block, then wait for the user to say "go" (or any affirmative: "yes", "launch", "start", "run it").

Show the input image thumbnail: read `tests/integration/fixtures/cake.jpg` using the Read tool so the image renders inline, immediately above the table.

```
Brickomancer Harness                               HEAD: <sha> ✓   Token ✓   Port 8005 ✓
─────────────────────────────────────────────────────────────────────────────────────────────
Image: tests/integration/fixtures/cake.jpg   Studs: 8   Tier: compact   Pieces: none   Iters: <N>

[cake.jpg rendered here]

  Dimension              raw  norm   Δ    Source files
  ─────────────────── ──────  ────  ───  ──────────────────────────────────────────────────
  part_variety           <r>  <n>   <Δ>  brick_packer.py
  shape_fidelity         <r>  <n>   <Δ>  image_pipeline.py
  build_stability        <r>  <n>   <Δ>  brick_packer.py · ldraw_writer.py
  instruction_clarity    <r>  <n>   <Δ>  ldraw_writer.py
  aesthetics             <r>  <n>   <Δ>  suggestion_service.py · subprocess_utils.py
  pdf_completeness       <r>  <n>   <Δ>  ldraw_writer.py · subprocess_utils.py
  technical_validity     <r>  <n>   <Δ>  ldraw_writer.py · brick_packer.py
                                         avg raw: <avg> / 7.0
```

Sort rows by raw score ascending (lowest first = most likely targets).

If a previous PDF exists, add below the table (as a clickable markdown link, outside the code block):
Previous PDF: [tests/harness/runs/iteration_N/instructions.pdf](tests/harness/runs/iteration_N/instructions.pdf)

Then: `Type "go" to launch.`

---

## Phase 3 — Launch

When the user says "go":

1. Run in background via Bash tool:
   ```bash
   cd /c/Users/abero/dev/brickomancer && PYTHONIOENCODING=utf-8 uv run python tests/harness/run_harness.py --iterations <N> > tests/harness/harness.log 2>&1 &
   echo $!
   ```
   Capture the PID from stdout.

2. Record `run_start_time` (current timestamp) and `run_start_sha` (`git rev-parse HEAD`).

3. Confirm: "Harness launched (PID <pid>). First update in 30 seconds."

4. Schedule the monitoring loop with ScheduleWakeup, passing this skill's prompt as the loop prompt with args `{"phase":"monitor","pid":<pid>,"iter":0,"N":<N>,"delays":[30,60,120,300],"run_start_sha":"<sha>"}`.

---

## Phase 4 — Monitor loop

On each ScheduleWakeup firing (and on "what's the status"):

### Read state

1. Read the last `N` rows of `tests/harness/scores.jsonl` (one row per completed iteration).
2. Read `tests/harness/harness.log` tail (last 30 lines) for in-progress signals.
3. Run `git log --oneline <run_start_sha>..HEAD` to list commits made this run.

### No iterations completed yet

If `scores.jsonl` has no new rows since run start:
```
── Harness  0/<N>  elapsed: <elapsed> ───────────────────────────────────────────────────────
  <status from harness.log tail — e.g. "pipeline running", "advisors evaluating">
```

### One or more iterations completed

For each new iteration since last update, show a compact block. When multiple finished since last check, show each (most recent last). Use this format:

```
── Iter <i>/<N>  elapsed: <elapsed> ─────────────────────────────────────────────────────────
  Result: <PASS_COMMITTED ✓ | SKIPPED_REVERT ✗ | SKIPPED_TIMEOUT ✗ | ...>   Selected: <dim>   Avg raw: <prev> → <cur> <▲/→/▼>
  Change: "<change_summary>"

  Dimension              raw  norm   sel
  ─────────────────── ──────  ────  ────
  <dim sorted by raw asc>    <r>  <n>    ✓    ← mark selected row
  ...                        <r>  <n>    —
                                         avg raw: <avg>   commits: <total committed>
  <commit sha>  <commit message>   (one line per commit made this run)
```

After the code block, add a PDF link if the file exists (clickable markdown link, outside the block):
[tests/harness/runs/iteration_<i>/instructions.pdf](tests/harness/runs/iteration_<i>/instructions.pdf)

### Schedule next wakeup

Use the delay sequence `[30, 60, 120, 300]` for the first four firings, then 600s (10 min) for all subsequent ones. Pass updated args (increment `iter` counter, pop the used delay) via ScheduleWakeup.

Stop scheduling when `scores.jsonl` shows `N` completed rows, or a `QUALITY_GATE_MET` entry appears, or the harness process is no longer running.

---

## Phase 5 — Completion

When the run is done (all iterations recorded, or quality gate met):

```
── Run complete  <done>/<N>  elapsed: <total> ───────────────────────────────────────────────

  Iter  Dimension           Result              Avg raw   Δ
  ────  ──────────────────  ──────────────────  ────────  ──────
  <one row per iteration from scores.jsonl>

  Final avg raw: <x> / 7.0   Committed: <n>   Reverted/skipped: <m>

  <sha>  <message>
  <sha>  <message>
```

Then:
1. Run `git push` from the project root.
2. After the code block, add a link for every PDF produced this run (one per committed iteration):
   [iteration_N/instructions.pdf](tests/harness/runs/iteration_N/instructions.pdf)
3. If final avg raw < `QUALITY_THRESHOLD` (8.0): "Pushed ✓  Run `/run-harness` again to continue hill-climbing."
4. If quality gate was met: "Quality gate reached (avg raw <x> ≥ 8.0). Pushed ✓"

---

## Handling "what's the status"

At any point during monitoring, if the user sends a status question ("what's the status", "how's it going", "any updates", etc.), immediately execute Phase 4's "Read state" and display steps inline — without waiting for the next scheduled wakeup. The wakeup timer continues unchanged.

---

## Constants (from run_harness.py)

- Server: `http://localhost:8005`
- Test image: `tests/integration/fixtures/cake.jpg`
- Stud height: `8`
- Tier: `compact`
- Scores log: `tests/harness/scores.jsonl`
- Harness log: `tests/harness/harness.log`
- Runs dir: `tests/harness/runs/`
- Quality threshold: `8.0` (avg raw)
- Dimension → source files mapping:
  - `shape_fidelity` → `image_pipeline.py`
  - `part_variety` → `brick_packer.py`
  - `build_stability` → `brick_packer.py · ldraw_writer.py`
  - `instruction_clarity` → `ldraw_writer.py`
  - `aesthetics` → `suggestion_service.py · subprocess_utils.py`
  - `pdf_completeness` → `ldraw_writer.py · subprocess_utils.py`
  - `technical_validity` → `ldraw_writer.py · brick_packer.py`

"""Applier: receives judge decision, writes the code change, gates with pytest, commits."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from tests.harness.judge import LPUB3D_META_REFERENCE, _LPUB_DIMENSIONS

log = logging.getLogger("harness")

APPLIER_TIMEOUT_S = 600


def _parse_applier_output(output: str) -> dict[str, Any] | None:
    """Extract JSON with a 'content' key from applier output."""
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict) and "content" in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    start = output.find("{")
    if start == -1:
        return None
    end = output.rfind("}")
    while end > start:
        try:
            parsed = json.loads(output[start : end + 1])
            if isinstance(parsed, dict) and "content" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        end = output.rfind("}", 0, end)
    return None


def _run_pytest(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "pytest", "-q", "--tb=short", "--ignore=tests/integration"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(project_root),
    )


def _build_applier_prompt(decision: dict[str, Any], current_content: str) -> str:
    dimension = decision["dimension"]
    file_path = decision["file_path"]
    rationale = decision["rationale"]
    approach = decision["approach_description"]
    functions = decision.get("functions_to_modify", [])
    constraints = decision.get("constraints_to_preserve", [])
    anti_patterns = decision.get("anti_patterns_to_avoid", [])

    fn_text = "\n".join(f"  - {f}" for f in functions) if functions else "  (judge did not specify)"
    constraint_text = "\n".join(f"  - {c}" for c in constraints) if constraints else "  (none specified)"
    anti_text = "\n".join(f"  - {a}" for a in anti_patterns) if anti_patterns else "  (none specified)"

    lpub_section = f"\n{LPUB3D_META_REFERENCE}\n" if dimension in _LPUB_DIMENSIONS else ""

    return (
        "You are a developer implementing a targeted improvement to a LEGO instruction PDF generator.\n\n"
        f"The judge has selected this change:\n"
        f"  Dimension:  {dimension}\n"
        f"  File:       {file_path}\n"
        f"  Rationale:  {rationale}\n"
        f"  Approach:   {approach}\n\n"
        f"Functions to modify:\n{fn_text}\n\n"
        f"Constraints to preserve:\n{constraint_text}\n\n"
        f"Anti-patterns to avoid:\n{anti_text}\n"
        f"{lpub_section}\n"
        f"Current file contents:\n--- {file_path} ---\n{current_content}\n--- end {file_path} ---\n\n"
        "Implement the judge's approach exactly as described. "
        "Do not add explanatory comments. Do not modify unrelated code. "
        "Do not deviate from the approach — if it seems wrong, implement it anyway and let tests decide.\n\n"
        "Output ONLY valid JSON on a single line:\n"
        f'{{"content": "<complete new file content>", "summary": "<one sentence describing the change>"}}'
    )


def apply(
    decision: dict[str, Any],
    iteration: int,
    project_root: Path,
) -> dict[str, Any]:
    """Apply the judge's decision: write file, run pytest, commit or revert.

    Returns {change_summary, test_result, dimension}.
    """
    dimension = decision["dimension"]
    rel_path = decision["file_path"]
    abs_target = project_root / rel_path

    def _skip(reason: str, summary: str | None = None) -> dict[str, Any]:
        return {"dimension": dimension, "change_summary": summary, "test_result": reason}

    # Blocking issues: judge said don't proceed
    blocking = decision.get("blocking_issues", [])
    if blocking:
        log.warning("apply: blocking issues present — skipping: %s", blocking)
        return _skip("SKIPPED_BLOCKED", "; ".join(blocking))

    if not abs_target.exists():
        log.warning("apply: target file does not exist: %s", abs_target)
        return _skip("SKIPPED_FILE_NOT_FOUND")

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        log.warning("apply: CLAUDE_CODE_OAUTH_TOKEN not set — skipping iter %d", iteration)
        return _skip("SKIPPED_NO_TOKEN")

    current_content = abs_target.read_text(encoding="utf-8")
    prompt = _build_applier_prompt(decision, current_content)
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token}

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=APPLIER_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log.warning("apply: Claude timed out on iteration %d", iteration)
        return _skip("SKIPPED_TIMEOUT")
    except OSError as exc:
        log.warning("apply: subprocess error: %s", exc)
        return _skip(f"SKIPPED_ERROR: {exc}")

    if proc.returncode != 0:
        log.warning("apply: Claude exited %d: %s", proc.returncode, proc.stderr[:200])
        return _skip(f"SKIPPED_SUBPROCESS_FAILED: exit={proc.returncode}")

    result_data = _parse_applier_output(proc.stdout.strip())
    if result_data is None:
        log.warning("apply: unparseable output (attempt 1): %s", proc.stdout[:300])
        retry_prompt = (
            "Your previous response was not valid JSON. You were implementing a code change "
            f"to {rel_path}. Your response was:\n\n{proc.stdout[:600]}\n\n"
            "Return ONLY a single line of valid JSON:\n"
            '{"content": "<complete new file content>", "summary": "<one sentence>"}'
        )
        try:
            retry = subprocess.run(
                ["claude", "-p", retry_prompt],
                capture_output=True, text=True, timeout=APPLIER_TIMEOUT_S, env=env,
            )
            result_data = _parse_applier_output(retry.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass
        if result_data is None:
            log.warning("apply: unparseable after retry")
            return _skip("SKIPPED_PARSE_ERROR")

    new_content: str = result_data.get("content", "")
    summary: str = str(result_data.get("summary", "(no summary)"))

    if not new_content:
        return _skip("SKIPPED_EMPTY_CONTENT", summary)

    abs_target.write_text(new_content, encoding="utf-8")
    log.info("apply: wrote %s (%d chars)", rel_path, len(new_content))

    test_proc = _run_pytest(project_root)

    if test_proc.returncode != 0:
        test_errors = (
            (test_proc.stdout[-3000:] if test_proc.stdout else "")
            + (test_proc.stderr[-500:] if test_proc.stderr else "")
        )
        log.warning("apply: pytest gate failed (attempt 1):\n%s", test_errors[-1000:])
        current_broken = abs_target.read_text(encoding="utf-8")
        fix_prompt = (
            f"You implemented a change to {rel_path} but it broke unit tests.\n\n"
            f"Failing tests:\n{test_errors}\n\n"
            f"Current file:\n--- {rel_path} ---\n{current_broken}\n--- end {rel_path} ---\n\n"
            "Fix ONLY the test failures — preserve the intent of the change. "
            "Return ONLY a single line of valid JSON:\n"
            f'{{"content": "<complete fixed file>", "summary": "<one sentence>"}}'
        )
        try:
            fix_proc = subprocess.run(
                ["claude", "-p", fix_prompt],
                capture_output=True, text=True, timeout=APPLIER_TIMEOUT_S, env=env,
            )
            fix_data = _parse_applier_output(fix_proc.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            fix_data = None

        if fix_data and fix_data.get("content"):
            abs_target.write_text(fix_data["content"], encoding="utf-8")
            summary = str(fix_data.get("summary", summary))
            log.info("apply: wrote test-fix retry to %s", rel_path)
            test_proc = _run_pytest(project_root)
            if test_proc.returncode == 0:
                log.info("apply: test-fix retry passed")
            else:
                log.warning("apply: pytest failed after retry — reverting %s", rel_path)
        else:
            log.warning("apply: test-fix retry unusable — reverting %s", rel_path)

    if test_proc.returncode == 0:
        git_add = subprocess.run(
            ["git", "add", rel_path],
            capture_output=True, text=True, cwd=str(project_root),
        )
        if git_add.returncode != 0:
            log.warning("apply: git add failed: %s", git_add.stderr[:200])
            return {"dimension": dimension, "change_summary": summary, "test_result": "PASS_ADD_FAILED"}

        normalized_score = 0.0  # judge doesn't surface this; commit msg omits it
        commit_msg = f"harness iter {iteration}: improve {dimension} via judge"
        git_commit = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True, text=True, cwd=str(project_root),
        )
        if git_commit.returncode == 0:
            log.info("apply: committed iter %d (%s)", iteration, dimension)
            test_result = "PASS_COMMITTED"
        else:
            log.warning("apply: git commit failed: %s", git_commit.stderr[:200])
            test_result = "PASS_COMMIT_FAILED"
    else:
        log.warning("apply: tests failed — reverting %s", rel_path)
        subprocess.run(
            ["git", "checkout", "--", rel_path],
            capture_output=True, text=True, cwd=str(project_root),
        )
        test_result = "SKIPPED_REVERT"

    return {"dimension": dimension, "change_summary": summary, "test_result": test_result}

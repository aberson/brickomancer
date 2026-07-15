"""Developer step: turn a judge decision into new file content via ``claude -p``.

Ported from the v1 applier's developer prompt (docs/rebuild_reference/applier.py
``_build_applier_prompt``), with the frozen ``CONSTRAINTS_TO_PRESERVE`` injected as hard
rules. Split out from the applier gate (Step 9) so the loop is: judge -> developer -> gate.
"""

from __future__ import annotations

import json
from typing import Any

from tests.harness._claude import HarnessLLMUnavailable, run_claude
from tests.harness.judge import CONSTRAINTS_TO_PRESERVE


def build_developer_prompt(decision: dict[str, Any], current_content: str) -> str:
    file_path = decision["file_path"]
    approach = decision.get("approach_description", "")
    rationale = decision.get("rationale", "")
    constraints_block = "\n".join(f"  - {c}" for c in sorted(CONSTRAINTS_TO_PRESERVE))
    return (
        "You are a developer implementing a targeted improvement to a LEGO instruction "
        "PDF generator.\n\n"
        f"Dimension:  {decision.get('dimension', '')}\n"
        f"File:       {file_path}\n"
        f"Rationale:  {rationale}\n"
        f"Approach:   {approach}\n\n"
        "## HARD CONSTRAINTS — the new content must NOT violate any of these:\n"
        f"{constraints_block}\n\n"
        f"Current file contents:\n--- {file_path} ---\n{current_content}\n"
        f"--- end {file_path} ---\n\n"
        "Implement the approach exactly. Do not modify unrelated code, do not add "
        "explanatory comments, and never touch a frozen constraint above.\n\n"
        "Output ONLY valid JSON on a single line:\n"
        '{"content": "<complete new file content>", "summary": "<one sentence>"}'
    )


def _parse_content(output: str) -> dict[str, Any] | None:
    """Extract a JSON object with a ``content`` key from claude output (whole, then braces)."""
    candidates = [output]
    start, end = output.find("{"), output.rfind("}")
    if start != -1 and end > start:
        candidates.append(output[start : end + 1])
    for text in candidates:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("content"), str):
            return parsed
    return None


def write_change(
    decision: dict[str, Any],
    current_content: str,
    *,
    run_claude_fn: Any = run_claude,
) -> tuple[str, str] | None:
    """Return ``(new_content, summary)`` for the decision, or None on any failure.

    None (LLM unavailable / unparseable / empty content) makes the loop SKIP the iteration
    rather than apply garbage — the gate would revert it anyway, but skipping is cheaper.
    """
    prompt = build_developer_prompt(decision, current_content)
    try:
        output = run_claude_fn(prompt)
    except HarnessLLMUnavailable:
        return None
    parsed = _parse_content(output)
    if parsed is None or not parsed["content"]:
        return None
    return parsed["content"], str(parsed.get("summary", ""))

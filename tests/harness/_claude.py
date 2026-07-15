"""Shared ``claude -p`` subprocess runner for the harness LLM steps (judge + developer).

Kept tiny and injectable so the loop's dry-test can substitute a fake without any real
subprocess / token. Mirrors the production OAUTH pattern (never ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import os
import subprocess

CLAUDE_TIMEOUT_S = 300


class HarnessLLMUnavailable(RuntimeError):
    """The claude CLI or its OAUTH token is unavailable, or the call failed/timed out."""


def run_claude(prompt: str, *, timeout: int = CLAUDE_TIMEOUT_S) -> str:
    """Run ``claude -p <prompt>`` and return stdout; raise HarnessLLMUnavailable on any failure."""
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        raise HarnessLLMUnavailable("CLAUDE_CODE_OAUTH_TOKEN not set")
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token},
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise HarnessLLMUnavailable(f"claude subprocess failed: {exc}") from exc
    if proc.returncode != 0:
        raise HarnessLLMUnavailable(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
    return proc.stdout

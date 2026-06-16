"""Server lifecycle: start, wait for readiness, terminate."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import httpx

log = logging.getLogger("harness")

POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 2.0


def start_server(server_port: int, log_path: Path) -> subprocess.Popen[bytes]:
    os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\Tools\LPub3D"
    log_fh = log_path.open("ab")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "--app-dir", "src", "brickomancer.main:app", "--port", str(server_port)],
        stdout=log_fh,
        stderr=log_fh,
    )
    log.info("Server process started (pid=%d); log → %s", proc.pid, log_path)
    return proc


def wait_for_server(status_url: str, timeout_s: float = POLL_TIMEOUT_S) -> bool:
    """Poll status_url until ldview_ok and lpub3d_ok are True, or timeout."""
    deadline = time.monotonic() + timeout_s
    log.info("Waiting for server to become ready (timeout=%ss)…", int(timeout_s))
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(status_url, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ldview_ok") and data.get("lpub3d_ok"):
                    log.info("Server ready: ldview_ok=True lpub3d_ok=True")
                    return True
                log.info(
                    "Server up but not ready yet: ldview_ok=%s lpub3d_ok=%s",
                    data.get("ldview_ok"),
                    data.get("lpub3d_ok"),
                )
        except httpx.HTTPError:
            pass
        time.sleep(POLL_INTERVAL_S)
    log.error("Server did not become ready within %ss", int(timeout_s))
    return False


def terminate_server(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    log.info("Terminating server process (pid=%d)…", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=10)
        log.info("Server process exited cleanly.")
    except subprocess.TimeoutExpired:
        log.warning("Server did not exit in 10s — sending kill.")
        proc.kill()
        proc.wait()
        log.info("Server process killed.")

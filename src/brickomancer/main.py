"""Brickomancer FastAPI application entry point."""

import asyncio
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from brickomancer.routers import generate, info
from brickomancer.services import data_service
from brickomancer.utils.temp_dir import TMP_DIR, TempDir  # noqa: F401

load_dotenv()


def _sweep_old_tmp_dirs() -> None:
    """Delete tmp/<uuid>/ subdirs older than 1 hour."""
    TMP_DIR.mkdir(exist_ok=True)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    for entry in TMP_DIR.iterdir():
        if not entry.is_dir():
            continue
        # Only process UUID-named directories
        try:
            uuid.UUID(entry.name)
        except ValueError:
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        except (FileNotFoundError, OSError):
            continue
        if mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup tasks: create tmp dir, sweep old tmp dirs, warm data service."""
    TMP_DIR.mkdir(exist_ok=True)
    _sweep_old_tmp_dirs()
    await asyncio.to_thread(data_service.initialize)
    yield


app = FastAPI(title="Brickomancer", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static/tmp", StaticFiles(directory=str(TMP_DIR)), name="static_tmp")

app.include_router(generate.router)
app.include_router(info.router)


def _check_command_on_path(*candidates: str) -> bool:
    """Return True if any of the candidate commands is found on PATH."""
    for cmd in candidates:
        if shutil.which(cmd) is not None:
            return True
    # Fallback: try `where` (Windows) for each candidate
    for cmd in candidates:
        try:
            result = subprocess.run(
                ["where", cmd],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return False


def _check_ldview_available() -> bool:
    """Return True if LDView is usable — checks LPub3D bundled binary first."""
    from brickomancer.utils.subprocess_utils import _LPUB3D_LDVIEW_CANDIDATES

    for p in _LPUB3D_LDVIEW_CANDIDATES:
        if Path(p).exists():
            return True
    return _check_command_on_path("LDView64", "LDView64.exe", "LDView", "ldview", "ldview.exe")


@app.get("/api/status")
async def status() -> dict:
    """Return service health status."""
    # Check llama-server
    llama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:8080/health")
            llama_ok = resp.status_code == 200
    except Exception:
        llama_ok = False

    ldview_ok = await asyncio.to_thread(_check_ldview_available)
    lpub3d_ok = await asyncio.to_thread(
        _check_command_on_path, "LPub3D", "LPub3D.exe", "lpub3d", "lpub3d.exe"
    )

    return {
        "status": "ok",
        "llama_server_ok": llama_ok,
        "ldview_ok": ldview_ok,
        "lpub3d_ok": lpub3d_ok,
    }

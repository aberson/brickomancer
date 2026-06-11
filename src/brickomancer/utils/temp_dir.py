"""Temporary directory context manager for per-request scratch space."""

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TMP_DIR = PROJECT_ROOT / "tmp"


@contextmanager
def TempDir() -> Generator[Path, None, None]:
    """Create a tmp/<uuid>/ directory, yield its path, and clean up on exit.

    Usage:
        with TempDir() as tmp:
            # tmp is a Path like tmp/550e8400-e29b-41d4-a716-446655440000/
            ...
    """
    request_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / request_id
    tmp_path.mkdir(parents=True, exist_ok=True)
    try:
        yield tmp_path
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)

"""Pipeline executor: POST to API, collect artifacts, return iteration state."""

from __future__ import annotations

import logging
import random
import shutil
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("harness")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pick_input_image(input_image_dir: Path) -> Path:
    candidates = sorted(p for p in input_image_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    if not candidates:
        raise FileNotFoundError(f"No images found in {input_image_dir}")
    return random.choice(candidates)


def pipeline_executor(
    server_url: str,
    tmp_dir: Path,
    runs_dir: Path,
    file_prefix: str,
    input_image_path: Path,
    height_studs: int,
) -> dict[str, Any]:
    """Run the full pipeline for one iteration and return iteration state."""
    with httpx.Client(timeout=300.0) as client:
        log.info("pipeline_executor: POSTing to /api/generate/from-image (image=%s) …", input_image_path.name)
        with input_image_path.open("rb") as img_fh:
            response = client.post(
                f"{server_url}/api/generate/from-image",
                files={"image": (input_image_path.name, img_fh, "image/jpeg")},
                data={"height_studs": str(height_studs)},
            )
        response.raise_for_status()
        generate_data: dict[str, Any] = response.json()

    suggestions: list[dict[str, Any]] = generate_data.get("suggestions", [])
    compact_suggestion: dict[str, Any] | None = next(
        (s for s in suggestions if s.get("tier") == "compact"), None
    )
    if compact_suggestion is None:
        raise ValueError("No compact suggestion in response")

    suggestion_id: str = compact_suggestion["id"]
    uuid_part, _tier_index = suggestion_id.rsplit("_", 1)

    with httpx.Client(timeout=120.0) as client:
        log.info("pipeline_executor: POSTing to /api/generate/instructions (suggestion_id=%s) …", suggestion_id)
        instr_response = client.post(
            f"{server_url}/api/generate/instructions",
            json={"suggestion_id": suggestion_id},
        )
        instr_response.raise_for_status()
        pdf_bytes = instr_response.content
        if not pdf_bytes:
            raise ValueError("instructions endpoint returned empty PDF bytes")

    pdf_path = runs_dir / f"{file_prefix}_instructions.pdf"
    pdf_path.write_bytes(pdf_bytes)
    log.info("pipeline_executor: PDF saved -> %s (%d bytes)", pdf_path, len(pdf_bytes))

    preview_src = tmp_dir / uuid_part / "suggestion_0_preview.png"
    preview_dst = runs_dir / f"{file_prefix}_preview.png"
    if preview_src.exists():
        shutil.copy2(preview_src, preview_dst)
        log.info("pipeline_executor: Preview PNG copied -> %s", preview_dst)
        preview_png_path = str(preview_dst)
    else:
        log.warning("pipeline_executor: Preview PNG not found at %s — continuing without it.", preview_src)
        preview_png_path = None

    return {
        "suggestion_id": suggestion_id,
        "uuid_part": uuid_part,
        "ldr_path": str(tmp_dir / uuid_part / "suggestion_0.ldr"),
        "preview_png_path": preview_png_path,
        "pdf_path": str(pdf_path),
        "input_image_path": str(input_image_path),
        "height_studs": height_studs,
    }

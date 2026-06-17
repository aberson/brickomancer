"""Generate router — image/text generation and instruction PDF endpoints."""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from brickomancer.models.schemas import (
    GenerateResponse,
    GenerateTextRequest,
    InstructionsRequest,
)
from brickomancer.services.instruction_service import ToolUnavailableError, generate_pdf
from brickomancer.utils.temp_dir import TMP_DIR

router = APIRouter()

# Phase 1 Step 1: the v1 shape pipelines were removed. The image path (silhouette+dome
# image_pipeline) is replaced by the 3D-model ImageShaper in Step 5; the text path
# (Llama text_pipeline) by the TextShaper in Step 6. Both routes return 503 until the
# Shaper seam (Step 2) and its implementations land. The route signatures are preserved
# so the frontend contract and FastAPI request validation are unchanged.
_SHAPER_PENDING = (
    "Shape generation is being rebuilt: the image/text Shaper seam and its "
    "implementations land in Phase 3 (Steps 5-6). This route returns 503 until then."
)


@router.post("/api/generate/from-image")
async def generate_from_image(
    image: UploadFile = File(...),
    piece_images: list[UploadFile] = File(default=[]),
    height_studs: int = Form(default=10),
) -> GenerateResponse:
    """Generate LEGO suggestions from an uploaded image.

    Temporarily stubbed (Phase 1 Step 1): the v1 silhouette+dome ``image_pipeline``
    was removed. The 3D-model ``ImageShaper`` lands in Step 5. The ``image`` parameter
    is kept required so FastAPI still returns 422 for a missing body; a present body
    returns 503 until the Shaper seam is wired.
    """
    raise HTTPException(status_code=503, detail=_SHAPER_PENDING)


@router.post("/api/generate/from-text")
async def generate_from_text(request: GenerateTextRequest) -> GenerateResponse:
    """Generate LEGO suggestions from a text description.

    Temporarily stubbed (Phase 1 Step 1): the v1 Llama ``text_pipeline`` was removed.
    The ``TextShaper`` lands in Step 6. Returns 503 until the Shaper seam is wired.
    """
    raise HTTPException(status_code=503, detail=_SHAPER_PENDING)


@router.post("/api/generate/instructions")
async def generate_instructions(request: InstructionsRequest) -> FileResponse:
    """Generate a step-by-step instruction PDF for a suggestion."""
    # Validate suggestion_id format: "<uuid>_<tier_index>"
    parts = request.suggestion_id.rsplit("_", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id format; expected <uuid>_<tier_index>",
        )
    uuid_part, tier_index_str = parts
    try:
        uuid.UUID(uuid_part)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id: UUID prefix is not a valid UUID",
        )
    try:
        tier_index = int(tier_index_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id: tier_index must be an integer",
        )

    ldr_path = TMP_DIR / uuid_part / f"suggestion_{tier_index}.ldr"
    if not ldr_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"LDraw file not found for suggestion_id={request.suggestion_id!r}",
        )

    try:
        pdf_path = generate_pdf(str(ldr_path), str(ldr_path.parent))
    except ToolUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )

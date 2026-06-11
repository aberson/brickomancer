"""Generate router — stubs for image/text generation and instructions."""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from brickomancer.models.schemas import GenerateTextRequest, InstructionsRequest

router = APIRouter()


@router.post("/api/generate/from-image")
async def generate_from_image() -> JSONResponse:
    """Generate LEGO suggestions from an uploaded image. (Not yet implemented.)"""
    return JSONResponse(status_code=501, content={"detail": "Not implemented"})


@router.post("/api/generate/from-text")
async def generate_from_text(request: GenerateTextRequest) -> JSONResponse:
    """Generate LEGO suggestions from a text description. (Not yet implemented.)"""
    return JSONResponse(status_code=501, content={"detail": "Not implemented"})


@router.post("/api/generate/instructions")
async def generate_instructions(request: InstructionsRequest) -> JSONResponse:
    """Generate a step-by-step instruction PDF for a suggestion. (Not yet implemented.)"""
    # Validate suggestion_id format: "<request_uuid>_<tier_index>"
    parts = request.suggestion_id.rsplit("_", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id format; expected <uuid>_<tier_index>",
        )
    uuid_part, tier_index = parts
    try:
        uuid.UUID(uuid_part)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id: UUID prefix is not a valid UUID",
        )
    try:
        int(tier_index)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid suggestion_id: tier_index must be an integer",
        )
    # ldr_path would be: tmp/<request_uuid>/suggestion_<tier_index>.ldr
    # (Construction shown here for documentation; not yet implemented)
    return JSONResponse(status_code=501, content={"detail": "Not implemented"})

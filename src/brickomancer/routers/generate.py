"""Generate router — image/text generation and instruction PDF endpoints."""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from brickomancer.models.brick import ColorMatch
from brickomancer.models.schemas import (
    GenerateResponse,
    GenerateTextRequest,
    InstructionsRequest,
)
from brickomancer.services import (
    color_service,
    image_pipeline,
    piece_detector,
    suggestion_service,
    text_pipeline,
)
from brickomancer.services.instruction_service import ToolUnavailableError, generate_pdf
from brickomancer.utils.temp_dir import TMP_DIR

router = APIRouter()


@router.post("/api/generate/from-image")
async def generate_from_image(
    image: UploadFile = File(...),
    piece_images: list[UploadFile] = File(default=[]),
    height_studs: int = Form(default=10),
) -> GenerateResponse:
    """Generate LEGO suggestions from an uploaded image."""
    request_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / request_id
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Write uploaded image to disk — use .name to strip any directory components
    # from the user-supplied filename and prevent path traversal.
    safe_name = Path(image.filename or "input.jpg").name or "input.jpg"
    image_path = tmp_path / safe_name
    image_bytes = await image.read()
    image_path.write_bytes(image_bytes)

    # Write piece images to disk
    piece_paths: list[str] = []
    for i, piece_file in enumerate(piece_images):
        safe_piece_name = Path(piece_file.filename or "piece.jpg").name or "piece.jpg"
        piece_path = tmp_path / f"piece_{i}_{safe_piece_name}"
        piece_bytes = await piece_file.read()
        piece_path.write_bytes(piece_bytes)
        piece_paths.append(str(piece_path))

    # Run image pipeline (raises ImportError if TripoSR not installed)
    try:
        grid = image_pipeline.run(str(image_path), height_studs)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Extract colors from image
    colors = color_service.extract_colors(str(image_path))

    # Detect pieces (optional; empty list if no piece images)
    piece_inventory = None
    if piece_paths:
        piece_inventory = piece_detector.detect_pieces(piece_paths)

    suggestions = suggestion_service.generate_suggestions(
        grid, colors, tmp_path, request_id, piece_inventory
    )
    return GenerateResponse(suggestions=suggestions)


@router.post("/api/generate/from-text")
async def generate_from_text(request: GenerateTextRequest) -> GenerateResponse:
    """Generate LEGO suggestions from a text description."""
    request_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / request_id
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Run text pipeline (raises ServiceUnavailableError if llama-server is down)
    try:
        grid = text_pipeline.run(request.description)
    except text_pipeline.ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # No image for color extraction — use default White
    default_color = ColorMatch(
        color_id=15,
        color_name="White",
        hex="F4F4F4",
        cluster_weight=1.0,
    )

    suggestions = suggestion_service.generate_suggestions(
        grid, [default_color], tmp_path, request_id
    )
    return GenerateResponse(suggestions=suggestions)


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

"""Generate router — image/text generation and instruction PDF endpoints."""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from brickomancer.models.brick import MAX_GRID_DIM, MIN_GRID_DIM
from brickomancer.models.schemas import (
    GenerateResponse,
    GenerateTextRequest,
    InstructionsRequest,
)
from brickomancer.services import color_service, piece_detector, suggestion_service
from brickomancer.services.image_shaper import ImageShaper, ModelUnavailableError
from brickomancer.services.instruction_service import ToolUnavailableError, generate_pdf
from brickomancer.services.text_shaper import TextShaper, TextShaperError
from brickomancer.utils.temp_dir import TMP_DIR

router = APIRouter()

# The text path has no source image to sample, so the build color is defaulted
# (the Shaper seam is geometry-only). LEGO bright red is a sensible neutral default.
_DEFAULT_TEXT_COLOR_HEX = "#C91A09"


@router.post("/api/generate/from-image")
async def generate_from_image(
    image: UploadFile = File(...),
    piece_images: list[UploadFile] = File(default=[]),
    height_studs: int = Form(default=10),
) -> GenerateResponse:
    """Generate LEGO suggestions from an uploaded image.

    Phase 3 Step 5: the upload is saved, run through the 3D-model ``ImageShaper``
    (rembg -> Hunyuan3D -> voxelize), colored from the same image, and packed into
    the three suggestion tiers. Returns 503 (not 500) when the model/GPU/weights are
    unavailable, so the rest of the local-first tool stays usable.
    """
    request_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / request_id
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Write the uploaded image to disk. Use .name to strip any directory components
    # from the user-supplied filename and prevent path traversal.
    safe_name = Path(image.filename or "input.jpg").name or "input.jpg"
    image_path = tmp_path / safe_name
    image_path.write_bytes(await image.read())

    # Write any piece images to disk for optional detection.
    piece_paths: list[str] = []
    for i, piece_file in enumerate(piece_images):
        safe_piece_name = Path(piece_file.filename or "piece.jpg").name or "piece.jpg"
        piece_path = tmp_path / f"piece_{i}_{safe_piece_name}"
        piece_path.write_bytes(await piece_file.read())
        piece_paths.append(str(piece_path))

    # Shape: image -> 3D model -> voxels. A missing GPU/install/weights is a 503.
    # height_studs is the user's resolution knob: the mesh's longest extent maps to
    # this many voxels. Clamped into the packer's footprint contract so any client
    # value is safe (28-ish is fine for star quality but packs too slowly per tier).
    resolution = max(MIN_GRID_DIM, min(MAX_GRID_DIM, height_studs))
    try:
        grid = ImageShaper(str(image_path), max_dim=resolution).to_voxels()
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Color is extracted separately from the same image (the seam is geometry-only).
    colors = color_service.extract_colors(str(image_path))

    # Detect pieces (optional soft constraint; empty/None when no piece images).
    piece_inventory = piece_detector.detect_pieces(piece_paths) if piece_paths else None

    try:
        suggestions = suggestion_service.generate_suggestions(
            grid, colors, tmp_path, request_id, piece_inventory
        )
    except RuntimeError as exc:  # e.g. LDView not on PATH (run_ldview)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return GenerateResponse(suggestions=suggestions)


@router.post("/api/generate/from-text")
async def generate_from_text(request: GenerateTextRequest) -> GenerateResponse:
    """Generate LEGO suggestions from a text description.

    Phase 3 Step 6: the description is run through ``TextShaper`` (a Claude CLI
    subprocess emits a sparse voxel occupancy), colored with a default brick color
    (the seam is geometry-only — text carries no source image), and packed into the
    three suggestion tiers. Returns 503 (not 500) when the Claude CLI is unavailable
    or never returns a usable voxel model.
    """
    request_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / request_id
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Shape: description -> Claude CLI sparse occupancy -> voxels. A CLI failure or
    # unusable model output (after retries) is a 503.
    try:
        grid = TextShaper(request.description).to_voxels()
    except TextShaperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Default the build color (geometry-only seam; no source image for text).
    colors = [color_service.match_color(_DEFAULT_TEXT_COLOR_HEX)]

    try:
        suggestions = suggestion_service.generate_suggestions(
            grid, colors, tmp_path, request_id
        )
    except RuntimeError as exc:  # e.g. LDView not on PATH (run_ldview)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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

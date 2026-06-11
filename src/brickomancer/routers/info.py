"""Info router — colors and status endpoints."""

from fastapi import APIRouter

from brickomancer.services import data_service

router = APIRouter()


@router.get("/api/colors")
async def list_colors() -> list:
    """Return available solid LEGO colors from LDConfig.ldr."""
    return data_service.list_colors()

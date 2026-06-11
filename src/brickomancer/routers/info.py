"""Info router — colors and status endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/colors")
async def list_colors() -> list:
    """Return available LEGO colors. (Stub — data layer implemented in Step 2.)"""
    return []

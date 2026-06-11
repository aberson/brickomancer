"""Pydantic schemas for Brickomancer API request/response models."""

from pydantic import BaseModel


class GenerateImageRequest(BaseModel):
    """Request for generating LEGO suggestions from an image."""

    height_studs: int = 10


class GenerateTextRequest(BaseModel):
    """Request for generating LEGO suggestions from a text description."""

    description: str
    height_studs: int = 10


class InstructionsRequest(BaseModel):
    """Request for generating instruction PDF for a given suggestion.

    suggestion_id format: '<request_uuid>_<tier_index>'
    where tier_index is 0=compact, 1=standard, 2=detailed.
    """

    suggestion_id: str


class PartCount(BaseModel):
    """A single part type with quantity and color information."""

    part_id: str
    color_name: str
    color_hex: str
    qty: int


class Suggestion(BaseModel):
    """A LEGO build suggestion for one complexity tier."""

    id: str
    tier: str
    preview_url: str
    parts_count: int
    parts_list: list[PartCount]


class GenerateResponse(BaseModel):
    """Response containing all LEGO build suggestions."""

    suggestions: list[Suggestion]

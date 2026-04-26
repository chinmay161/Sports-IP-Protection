"""Schemas for DMCA draft generation."""
from pydantic import BaseModel, ConfigDict


class DraftDmcaResponse(BaseModel):
    """The AI-generated draft, plus provenance info for the UI."""
    notice: str
    provider: str  # "gemini" | "fallback"
    model: str | None  # model name when provider == "gemini"

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "notice": "DMCA TAKEDOWN NOTICE...",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
        }
    })
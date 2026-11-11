"""Request/response models for /api/v1."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...dag.context import TripResult
from ...domain.models import PlanDraft


class TripPlanResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: TripResult
    trip_id: str
    request_id: str = Field(default="")
    cached: bool = False


class RecalculateRequest(BaseModel):
    plan: PlanDraft | None = None

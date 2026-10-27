"""DAG execution context, node results and trace events.

The walking skeleton (Day 1) and the real DAG executor (Day 2) share these
contracts. Keeping them in one place makes the eventual executor swappable.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import (
    AttractionCandidate,
    BudgetReport,
    DayPlanDraft,
    Facts,
    Narrative,
    PlanDraft,
    TripRequest,
    ValidationResult,
)


class NodeStatus(str, Enum):
    ok = "ok"
    degraded = "degraded"
    failed = "failed"
    skipped = "skipped"


class NodeResult(BaseModel):
    """Uniform result returned by every DAG node."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: NodeStatus
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, **meta: Any) -> "NodeResult":
        return cls(status=NodeStatus.ok, data=data, meta=meta)

    @classmethod
    def degraded(
        cls, data: Any = None, error: str = "", **meta: Any
    ) -> "NodeResult":
        return cls(
            status=NodeStatus.degraded,
            data=data,
            error=error or None,
            meta=meta,
        )

    @classmethod
    def failed(cls, error: str, **meta: Any) -> "NodeResult":
        return cls(status=NodeStatus.failed, error=error, meta=meta)


class TraceEvent(BaseModel):
    node_id: str
    status: NodeStatus
    duration_ms: float = 0.0
    cache: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TripContext(BaseModel):
    """Per-request state. No global agent history, no cross-request state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: TripRequest
    facts: Facts | None = None
    candidates: list[AttractionCandidate] = Field(default_factory=list)
    plan: PlanDraft | None = None
    validation: ValidationResult | None = None
    budget: BudgetReport | None = None
    narrative: Narrative | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    degraded: bool = False
    errors: list[str] = Field(default_factory=list)

    def record(
        self,
        node_id: str,
        result: NodeResult,
        duration_ms: float = 0.0,
        **meta: Any,
    ) -> TraceEvent:
        event = TraceEvent(
            node_id=node_id,
            status=result.status,
            duration_ms=round(duration_ms, 2),
            error=result.error,
            meta={**result.meta, **meta},
        )
        self.trace.append(event)
        if result.status == NodeStatus.degraded:
            self.degraded = True
            if result.error:
                self.errors.append(result.error)
        elif result.status == NodeStatus.failed:
            self.errors.append(result.error or f"{node_id} failed")
        return event

    def mark_degraded(self, reason: str) -> None:
        self.degraded = True
        if reason:
            self.errors.append(reason)

    def selected_attraction_ids(self) -> list[str]:
        if self.plan is None:
            return []
        return [
            attraction_id
            for day in self.plan.days
            for attraction_id in day.attraction_ids
        ]


# ---------------------------------------------------------------------------
# Rendered response views (Day 1 walking skeleton / future API response)
# ---------------------------------------------------------------------------
class AttractionView(BaseModel):
    id: str
    name: str
    area: str
    ticket_price: int
    duration_min: int
    description: str = ""
    must_see: bool = False
    indoor: bool = False
    walking_level: int = 2


class HotelView(BaseModel):
    id: str
    name: str
    tier: str
    area: str
    price_per_night: int


class MealView(BaseModel):
    type: str
    restaurant_id: str
    name: str
    avg_price: int
    area: str


class DayView(BaseModel):
    date: str
    day_index: int
    theme: str = ""
    transport_mode: str = "公共交通"
    attractions: list[AttractionView] = Field(default_factory=list)
    hotel: HotelView | None = None
    meals: list[MealView] = Field(default_factory=list)


class TripResult(BaseModel):
    request: TripRequest
    days: list[DayView]
    budget: BudgetReport
    validation: ValidationResult
    trace: list[TraceEvent] = Field(default_factory=list)
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)

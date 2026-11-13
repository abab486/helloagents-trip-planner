"""Shared test fixtures/helpers (not collected by pytest)."""

from __future__ import annotations

import time
from datetime import date, timedelta

from app.agents.planner import PlannerResult
from app.domain.models import DayPlanDraft, MealChoice, PlanDraft, TripRequest


def make_request(
    days: int = 2,
    *,
    start: str = "2026-11-01",
    budget: int | None = 800,
    **overrides,
) -> TripRequest:
    start_date = date.fromisoformat(start)
    end_date = start_date + timedelta(days=days - 1)
    values = {
        "city": "镇江",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "travel_days": days,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["历史文化"],
        "budget_limit": budget,
    }
    values.update(overrides)
    return TripRequest(**values)


def make_plan(request: TripRequest, hotel_id: str = "H002") -> PlanDraft:
    attraction_pairs = [
        ("A001", "A002"),
        ("A005", "A006"),
        ("A007", "A008"),
    ]
    start = date.fromisoformat(request.start_date)
    days: list[DayPlanDraft] = []
    for index in range(request.travel_days):
        first, second = attraction_pairs[index % len(attraction_pairs)]
        days.append(
            DayPlanDraft(
                date=(start + timedelta(days=index)).isoformat(),
                attraction_ids=[first, second],
                hotel_id=hotel_id,
                meals=[
                    MealChoice(type="breakfast", restaurant_id="R004"),
                    MealChoice(type="lunch", restaurant_id="R006"),
                    MealChoice(type="dinner", restaurant_id="R001"),
                ],
                transport_mode="公共交通",
                theme="历史文化",
            )
        )
    return PlanDraft(days=days, notes=["fake planner"])


class FakePlanner:
    """Duck-typed PlannerAgent for API/service tests; no network."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    def plan(self, request: TripRequest, facts) -> PlannerResult:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        plan = make_plan(request)
        return PlannerResult(
            plan=plan,
            attempts=1,
            model="fake-model",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=1.0,
        )

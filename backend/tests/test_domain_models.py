"""Domain contract tests: validation, budget identity and DAG context."""

import pytest
from pydantic import ValidationError

from app.dag.context import NodeResult, NodeStatus, TraceEvent, TripContext
from app.domain.models import (
    BudgetLine,
    BudgetReport,
    DayPlanDraft,
    MealChoice,
    PlanDraft,
    TripRequest,
    ValidationResult,
)


def make_request(**overrides) -> TripRequest:
    values = {
        "city": "镇江",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "travel_days": 2,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["历史文化"],
        "budget_limit": 800,
    }
    values.update(overrides)
    return TripRequest(**values)


def test_valid_request():
    request = make_request()
    assert request.city == "镇江"
    assert request.travel_days == 2


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        make_request(
            start_date="2026-11-03",
            end_date="2026-11-01",
        )


def test_days_must_match_date_range():
    with pytest.raises(ValidationError):
        make_request(
            start_date="2026-11-01",
            end_date="2026-11-03",
            travel_days=2,
        )


def test_only_zhenjiang_supported():
    with pytest.raises(ValidationError):
        make_request(city="南京")


def test_unknown_transport_rejected():
    with pytest.raises(ValidationError):
        make_request(transportation="火箭")


def test_free_text_is_bounded():
    with pytest.raises(ValidationError):
        make_request(free_text_input="x" * 501)


def test_plan_draft_rejects_duplicate_dates():
    day = DayPlanDraft(
        date="2026-11-01",
        attraction_ids=["A001"],
        hotel_id="H001",
        meals=[MealChoice(type="breakfast", restaurant_id="R001")],
    )
    with pytest.raises(ValidationError):
        PlanDraft(days=[day, day])


def test_budget_identity_is_enforced():
    lines = [
        BudgetLine(category="attraction", ref_id="A001", name="金山寺", amount=65),
        BudgetLine(category="hotel", ref_id="H001", name="酒店", amount=200),
    ]
    report = BudgetReport.from_lines(lines, budget_limit=300)
    assert report.total == 265
    assert report.over_budget == 0
    assert report.total_by("attraction") == 65

    with pytest.raises(ValidationError):
        BudgetReport(lines=lines, total=0, budget_limit=300)


def test_validation_result_blocking_semantics():
    result = ValidationResult()
    assert result.passed is True

    result.add("WARN", "只是提醒", severity="warning")
    assert result.passed is True

    result.add("BLOCK", "必须修复")
    assert result.passed is False
    assert result.has_blocking is True


def test_node_result_helpers():
    assert NodeResult.ok({"x": 1}).status == NodeStatus.ok
    assert NodeResult.degraded(error="weather timeout").status == NodeStatus.degraded
    assert NodeResult.failed("boom").status == NodeStatus.failed


def test_trip_context_records_trace_and_degradation():
    context = TripContext(request=make_request())
    context.record("load", NodeResult.ok({"n": 18}), duration_ms=12.3)
    context.record(
        "weather",
        NodeResult.degraded(error="timeout", source="climate"),
        duration_ms=4.0,
    )

    assert len(context.trace) == 2
    assert isinstance(context.trace[0], TraceEvent)
    assert context.trace[0].duration_ms == 12.3
    assert context.degraded is True
    assert "timeout" in context.errors

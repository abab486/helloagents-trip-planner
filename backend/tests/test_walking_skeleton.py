"""Day 1 walking skeleton end-to-end tests (CSV + fake planner, no LLM/DB)."""

import json

from app.dag.walking_skeleton import run_walking_skeleton
from app.data.loader import load_facts
from app.domain.models import TripRequest


def make_request(days: int = 2, budget: int = 800, **overrides) -> TripRequest:
    values = {
        "city": "镇江",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "travel_days": days,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["历史文化"],
        "budget_limit": budget,
    }
    if days == 3:
        values["end_date"] = "2026-11-03"
    values.update(overrides)
    return TripRequest(**values)


def test_loader_builds_facts():
    facts = load_facts("2026-11-01", 2)
    assert len(facts.attractions) == 18
    assert len(facts.hotels) == 10
    assert len(facts.restaurants) == 12
    assert len(facts.transports) == 8
    assert len(facts.weather) == 2
    assert len(facts.must_see_attractions) == 8
    assert [item.date for item in facts.weather] == ["2026-11-01", "2026-11-02"]
    assert len({item.id for item in facts.attractions}) == 18


def test_two_day_plan_is_valid_and_budget_balanced():
    result = run_walking_skeleton(make_request(days=2, budget=800))

    assert len(result.days) == 2
    assert result.validation.passed is True
    assert result.budget.over_budget == 0
    assert result.budget.total == sum(line.amount for line in result.budget.lines)
    assert result.budget.budget_limit == 800

    ids = [
        attraction.id
        for day in result.days
        for attraction in day.attractions
    ]
    assert len(ids) == len(set(ids))
    assert "A001" in ids
    assert all(2 <= len(day.attractions) <= 3 for day in result.days)
    assert all(len(day.meals) == 3 for day in result.days)


def test_trace_has_expected_nodes():
    result = run_walking_skeleton(make_request())
    assert [event.node_id for event in result.trace] == [
        "load_dataset",
        "fake_plan",
        "validate",
        "budget",
        "render",
    ]
    assert all(event.status.value == "ok" for event in result.trace)


def test_result_is_json_serializable():
    result = run_walking_skeleton(make_request())
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "金山寺" in payload
    assert "budget" in payload


def test_three_day_plan_is_valid():
    result = run_walking_skeleton(make_request(days=3, budget=1500))
    assert len(result.days) == 3
    assert result.validation.passed is True
    ids = [
        attraction.id
        for day in result.days
        for attraction in day.attractions
    ]
    assert len(ids) == 6
    assert len(ids) == len(set(ids))


def test_one_day_over_budget_is_flagged_but_plan_is_still_valid():
    result = run_walking_skeleton(make_request(days=1, budget=300, end_date="2026-11-01"))
    assert result.validation.passed is True
    assert result.budget.over_budget > 0
    assert result.budget.total > 300


def test_monday_does_not_schedule_closed_museum():
    # A004 镇江博物馆 is marked closed on Monday (0); 2026-11-02 is Monday.
    result = run_walking_skeleton(
        make_request(
            days=1,
            start_date="2026-11-02",
            end_date="2026-11-02",
        )
    )
    ids = [
        attraction.id
        for day in result.days
        for attraction in day.attractions
    ]
    assert "A004" not in ids


def test_elderly_request_avoids_high_walking_attractions():
    result = run_walking_skeleton(
        make_request(days=3, budget=1500, party="elderly")
    )
    levels = [
        attraction.walking_level
        for day in result.days
        for attraction in day.attractions
    ]
    assert max(levels) <= 2

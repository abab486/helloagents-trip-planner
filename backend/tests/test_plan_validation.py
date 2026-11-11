"""Day 3 validation tests: hard constraints must fail before the UI sees a plan."""

from app.dag.walking_skeleton import budget_plan, validate_plan
from app.data.loader import load_facts
from app.domain.models import PlanDraft, TripRequest


def make_request(start: str = "2026-11-01", end: str = "2026-11-02") -> TripRequest:
    return TripRequest(
        city="镇江",
        start_date=start,
        end_date=end,
        travel_days=2,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
        budget_limit=800,
    )


def valid_plan() -> dict:
    return {
        "days": [
            {
                "date": "2026-11-01",
                "attraction_ids": ["A001", "A002"],
                "hotel_id": "H002",
                "meals": [
                    {"type": "breakfast", "restaurant_id": "R004"},
                    {"type": "lunch", "restaurant_id": "R002"},
                    {"type": "dinner", "restaurant_id": "R008"},
                ],
                "transport_mode": "公共交通",
                "theme": "历史文化",
            },
            {
                "date": "2026-11-02",
                "attraction_ids": ["A005", "A006"],
                "hotel_id": "H002",
                "meals": [
                    {"type": "breakfast", "restaurant_id": "R004"},
                    {"type": "lunch", "restaurant_id": "R006"},
                    {"type": "dinner", "restaurant_id": "R001"},
                ],
                "transport_mode": "公共交通",
                "theme": "历史文化",
            },
        ]
    }


def test_valid_plan_passes():
    facts = load_facts("2026-11-01", 2)
    plan = PlanDraft.model_validate(valid_plan())
    result = validate_plan(plan, facts, make_request())
    assert result.passed is True
    assert result.issues == []


def test_duplicate_attraction_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][1]["attraction_ids"] = ["A001", "A006"]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "DUPLICATE_ATTRACTION" for issue in result.issues)


def test_unknown_attraction_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][0]["attraction_ids"] = ["A999", "A002"]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "UNKNOWN_ATTRACTION" for issue in result.issues)


def test_closed_day_is_blocking():
    facts = load_facts("2026-11-02", 2)
    data = valid_plan()
    data["days"][0]["date"] = "2026-11-02"
    data["days"][1]["date"] = "2026-11-03"
    data["days"][0]["attraction_ids"] = ["A004", "A002"]  # A004 closed Monday
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request("2026-11-02", "2026-11-03"))

    assert result.passed is False
    assert any(issue.code == "CLOSED_DAY" for issue in result.issues)


def test_missing_meal_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][0]["meals"] = data["days"][0]["meals"][:2]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "MISSING_MEAL" for issue in result.issues)


def test_budget_over_limit_keeps_identity():
    facts = load_facts("2026-11-01", 2)
    plan = PlanDraft.model_validate(valid_plan())
    request = make_request()
    request = request.model_copy(update={"budget_limit": 300})

    report = budget_plan(plan, facts, request)

    assert report.total == sum(line.amount for line in report.lines)
    assert report.over_budget > 0
    assert report.over_budget == report.total - 300

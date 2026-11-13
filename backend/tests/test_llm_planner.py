"""Day 3 tests: LLM Planner structured output, repair retry and LLM DAG."""

import json

import pytest

from app.agents.planner import PlannerAgent, PlannerError
from app.dag.llm_pipeline import run_llm_pipeline
from app.data.loader import load_facts
from app.domain.models import TripRequest
from app.llm.client import LLMResult


def make_request(days: int = 2, budget: int = 800) -> TripRequest:
    return TripRequest(
        city="镇江",
        start_date="2026-11-01",
        end_date="2026-11-02" if days == 2 else "2026-11-03",
        travel_days=days,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
        budget_limit=budget,
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
        ],
        "notes": ["test plan"],
    }


class FakeLLM:
    def __init__(self, contents: list[str | Exception]) -> None:
        self.contents = contents
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages, **kwargs) -> LLMResult:
        index = len(self.calls)
        self.calls.append(list(messages))
        content = self.contents[min(index, len(self.contents) - 1)]
        if isinstance(content, Exception):
            raise content
        return LLMResult(
            content=content,
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=1.0,
        )


def test_planner_returns_valid_plan():
    llm = FakeLLM([json.dumps(valid_plan(), ensure_ascii=False)])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 1
    assert len(result.plan.days) == 2
    assert result.plan.days[0].attraction_ids == ["A001", "A002"]
    assert result.total_tokens == 150
    assert result.prompt_version == "planner_v1"


def test_planner_repairs_invalid_json():
    llm = FakeLLM(["这不是 JSON", json.dumps(valid_plan(), ensure_ascii=False)])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert any("不合法" in message["content"] for message in llm.calls[1])


def test_planner_repairs_unknown_id():
    bad = valid_plan()
    bad["days"][0]["attraction_ids"] = ["A999", "A002"]
    llm = FakeLLM([json.dumps(bad), json.dumps(valid_plan())])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 2
    assert result.plan.days[0].attraction_ids == ["A001", "A002"]


def test_planner_raises_after_retries_without_fake_plan():
    llm = FakeLLM(["bad", "still bad"])
    facts = load_facts("2026-11-01", 2)

    with pytest.raises(PlannerError):
        PlannerAgent(llm).plan(make_request(), facts)


def test_planner_accepts_fenced_json():
    fenced = "```json\n" + json.dumps(valid_plan(), ensure_ascii=False) + "\n```"
    llm = FakeLLM([fenced])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)
    assert result.attempts == 1


def test_planner_repairs_closed_day():
    # 2026-11-02 is Monday; A004 is closed on Monday.
    bad = valid_plan()
    bad["days"][0]["date"] = "2026-11-02"
    bad["days"][1]["date"] = "2026-11-03"
    bad["days"][0]["attraction_ids"] = ["A004", "A002"]

    good = valid_plan()
    good["days"][0]["date"] = "2026-11-02"
    good["days"][1]["date"] = "2026-11-03"
    good["days"][0]["attraction_ids"] = ["A001", "A002"]

    request = TripRequest(
        city="镇江",
        start_date="2026-11-02",
        end_date="2026-11-03",
        travel_days=2,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
        budget_limit=800,
    )
    facts = load_facts("2026-11-02", 2)
    llm = FakeLLM([json.dumps(bad), json.dumps(good)])

    result = PlannerAgent(llm).plan(request, facts)

    assert result.attempts == 2
    assert result.plan.days[0].attraction_ids == ["A001", "A002"]


def test_planner_rejects_missing_meal():
    bad = valid_plan()
    bad["days"][0]["meals"] = bad["days"][0]["meals"][:2]
    llm = FakeLLM([json.dumps(bad), json.dumps(bad)])
    facts = load_facts("2026-11-01", 2)

    with pytest.raises(PlannerError):
        PlannerAgent(llm).plan(make_request(), facts)


def test_llm_pipeline_uses_planner_and_dag():
    llm = FakeLLM([json.dumps(valid_plan(), ensure_ascii=False)])
    planner = PlannerAgent(llm)

    result = run_llm_pipeline(make_request(), planner)

    assert len(result.days) == 2
    assert result.validation.passed is True
    assert result.budget.total == sum(line.amount for line in result.budget.lines)
    assert [event.node_id for event in result.trace] == [
        "load_dataset",
        "plan",
        "validate",
        "budget",
        "render",
    ]
    plan_event = next(event for event in result.trace if event.node_id == "plan")
    assert plan_event.meta["planner_attempts"] == 1
    assert plan_event.meta["total_tokens"] == 150


def test_llm_pipeline_fails_loudly_instead_of_fake_plan():
    llm = FakeLLM(["bad", "still bad"])
    planner = PlannerAgent(llm)

    with pytest.raises(RuntimeError, match="LLM 规划失败"):
        run_llm_pipeline(make_request(), planner)

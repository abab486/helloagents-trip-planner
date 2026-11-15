"""Day 3 测试：LLM Planner 的结构化输出、repair 重试与 LLM 版 DAG。

分两段：前半段只测 PlannerAgent（用 FakeLLM 隔离网络），
后半段测整条 LLM 链路（五节点 trace + 失败必须响亮）。
"""

import json

import pytest

from app.agents.planner import PlannerAgent, PlannerError
from app.dag.llm_pipeline import run_llm_pipeline
from app.data.loader import load_facts
from app.domain.models import TripRequest
from app.llm.client import LLMResult


# 两天基准请求；days != 2 时结束日期顺延到 11-03
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


# 一份合法计划，各用例在它上面做单点破坏，用来验证 repair 是否真的修好了
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


# 假 LLM：按调用顺序吐预设内容，元素是 Exception 就抛（模拟网络失败）。
# calls 记录每次的 messages，用来断言 repair 有没有把错误提示回灌给模型
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


# 一次就成：attempts=1，token 统计和 prompt 版本随结果一起返回
# （这两个字段是评测统计成本的入口）
def test_planner_returns_valid_plan():
    llm = FakeLLM([json.dumps(valid_plan(), ensure_ascii=False)])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 1
    assert len(result.plan.days) == 2
    assert result.plan.days[0].attraction_ids == ["A001", "A002"]
    assert result.total_tokens == 150
    assert result.prompt_version == "planner_v1"


# 第一次不是 JSON：repair 要把"不合法"的提示回灌给模型再问一次，
# 所以断言三件事——重试了 2 次、发了 2 轮 messages、第二轮里带着错误说明
def test_planner_repairs_invalid_json():
    llm = FakeLLM(["这不是 JSON", json.dumps(valid_plan(), ensure_ascii=False)])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert any("不合法" in message["content"] for message in llm.calls[1])


# 第一次选了不存在的 A999：靠 PlannerAgent._validate_ids 早筛拦住（还没到
# validate_plan），第二次换成合法 ID 就通过
def test_planner_repairs_unknown_id():
    bad = valid_plan()
    bad["days"][0]["attraction_ids"] = ["A999", "A002"]
    llm = FakeLLM([json.dumps(bad), json.dumps(valid_plan())])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)

    assert result.attempts == 2
    assert result.plan.days[0].attraction_ids == ["A001", "A002"]


# 两次都给坏数据：直接抛 PlannerError。
# 这条守的是项目底线——修不好就报错，不许退化成一份假计划
def test_planner_raises_after_retries_without_fake_plan():
    llm = FakeLLM(["bad", "still bad"])
    facts = load_facts("2026-11-01", 2)

    with pytest.raises(PlannerError):
        PlannerAgent(llm).plan(make_request(), facts)


# 模型爱在外面套 ```json 围栏：要能剥掉围栏正常解析，
# 这不算失败，attempts 仍然是 1
def test_planner_accepts_fenced_json():
    fenced = "```json\n" + json.dumps(valid_plan(), ensure_ascii=False) + "\n```"
    llm = FakeLLM([fenced])
    facts = load_facts("2026-11-01", 2)

    result = PlannerAgent(llm).plan(make_request(), facts)
    assert result.attempts == 1


# 闭馆日也要能早筛：第一天排了周一闭馆的 A004（2026-11-02 是周一），
# 修好后换成 A001。注意请求和 facts 的日期都得跟着改成 11-02 起
def test_planner_repairs_closed_day():
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


# 少一顿饭且两轮都没修好 -> PlannerError。
# 和上面"ID 不存在"的区别：这是结构性缺陷，模型连续两次犯同一个错就该放弃
def test_planner_rejects_missing_meal():
    bad = valid_plan()
    bad["days"][0]["meals"] = bad["days"][0]["meals"][:2]
    llm = FakeLLM([json.dumps(bad), json.dumps(bad)])
    facts = load_facts("2026-11-01", 2)

    with pytest.raises(PlannerError):
        PlannerAgent(llm).plan(make_request(), facts)


# 整条 LLM 链路：五节点 trace 齐全、校验通过、预算恒等；
# plan 节点那条 trace 里带 attempts 和 token —— 评测脚本就是从这里取数的
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


# 全链路底线：Planner 修不好 -> plan 节点 failed -> 下游全 skipped
# -> 抛 RuntimeError（到 API 就是 502），绝不返回编造的行程
def test_llm_pipeline_fails_loudly_instead_of_fake_plan():
    llm = FakeLLM(["bad", "still bad"])
    planner = PlannerAgent(llm)

    with pytest.raises(RuntimeError, match="LLM 规划失败"):
        run_llm_pipeline(make_request(), planner)

"""Day 1 走路骨架的端到端测试（读 CSV + 规则规划器，不碰 LLM/DB）。

这里跑的是评测里的 rule 基线：零 Token、毫秒级，
它的作用是证明"校验 + 预算链路本身是通的"。
"""

import json

from app.dag.walking_skeleton import run_walking_skeleton
from app.data.loader import load_facts
from app.domain.models import TripRequest


# 默认两天、公共交通、经济型的请求；days=3 时顺手把结束日期改掉
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


# 数据加载的口径：18 景点 / 10 酒店 / 12 餐厅 / 8 交通 / 2 天假天气，
# ID 不重复，天气日期和行程日期一一对应
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


# 基准行程：结构合法、不超预算、四项之和等于 total（预算恒等）、
# 景点不重复、每天 2–3 个、三餐齐全
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


# trace 必须覆盖五个节点、顺序正确、状态全 ok（前端时间轴直接读它）
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


# 结果要能直接丢给前端：ID 已经展开成中文名（"金山寺"），
# 而不是还留着 A001
def test_result_is_json_serializable():
    result = run_walking_skeleton(make_request())
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "金山寺" in payload
    assert "budget" in payload


# 三天 6 个景点，且不重复（规则规划器靠 selected 集合去重）
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


# 超预算只标记、不拦截：validation 照样 passed，只有 budget.over_budget > 0。
# （顺带这条例子里含一晚"不存在的房费"——nights = max(days-1, 1)）
def test_one_day_over_budget_is_flagged_but_plan_is_still_valid():
    result = run_walking_skeleton(make_request(days=1, budget=300, end_date="2026-11-01"))
    assert result.validation.passed is True
    assert result.budget.over_budget > 0
    assert result.budget.total > 300


# _eligible 的第一道门槛：A004 镇江博物馆周一闭馆（closed_day=0），
# 2026-11-02 正是周一，规则规划器不能把它排进去
def test_monday_does_not_schedule_closed_museum():
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


# _eligible 的第三道门槛：带老人时步行强度 ≥3 的景点全部排除。
# 注意这条只对 fake_plan 生效，validate_plan 并不查 walking_level
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

"""Day 3 校验测试：硬约束必须在前端看到行程之前就失败。

每个用例都从"标准答案"出发只破坏一处，这样断言的是单条规则，
而不是一堆规则混在一起的结果。
"""

from app.dag.walking_skeleton import budget_plan, validate_plan
from app.data.loader import load_facts
from app.domain.models import PlanDraft, TripRequest


# 两天基准请求，只看日期范围，其余字段不影响校验规则
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


# 一份"标准答案"计划：两天、每天 2 个景点、三餐齐全、酒店同区。
# 各用例在它上面做单点破坏，改完仍然能构造成功（schema 层不拦），交给 validate_plan 判
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


# 基线：什么都不改，一条 issue 都不该有（后面所有失败用例都靠它作对照）
def test_valid_plan_passes():
    facts = load_facts("2026-11-01", 2)
    plan = PlanDraft.model_validate(valid_plan())
    result = validate_plan(plan, facts, make_request())
    assert result.passed is True
    assert result.issues == []


# 第二天又排了一次 A001 -> DUPLICATE_ATTRACTION，阻塞
def test_duplicate_attraction_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][1]["attraction_ids"] = ["A001", "A006"]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "DUPLICATE_ATTRACTION" for issue in result.issues)


# A999 在 CSV 里不存在（典型幻觉）-> UNKNOWN_ATTRACTION。
# 这是"LLM 只输出 ID"设计的第一道网：选错 ID 可以被 100% 检测
def test_unknown_attraction_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][0]["attraction_ids"] = ["A999", "A002"]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "UNKNOWN_ATTRACTION" for issue in result.issues)


# 周一（2026-11-02）排了闭馆的 A004 博物馆 -> CLOSED_DAY
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


# 砍掉晚饭 -> MISSING_MEAL，阻塞（早/午/晚三顿缺一不可）
def test_missing_meal_is_blocking():
    facts = load_facts("2026-11-01", 2)
    data = valid_plan()
    data["days"][0]["meals"] = data["days"][0]["meals"][:2]
    plan = PlanDraft.model_validate(data)

    result = validate_plan(plan, facts, make_request())

    assert result.passed is False
    assert any(issue.code == "MISSING_MEAL" for issue in result.issues)


# 超预算不破坏恒等式：total 仍等于四项之和，
# over_budget 恰好等于 total - limit（这条由 BudgetReport 的 model_validator 兜底）
def test_budget_over_limit_keeps_identity():
    facts = load_facts("2026-11-01", 2)
    plan = PlanDraft.model_validate(valid_plan())
    request = make_request()
    request = request.model_copy(update={"budget_limit": 300})

    report = budget_plan(plan, facts, request)

    assert report.total == sum(line.amount for line in report.lines)
    assert report.over_budget > 0
    assert report.over_budget == report.total - 300

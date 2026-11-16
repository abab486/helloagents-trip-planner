"""领域契约测试：请求校验、预算恒等式、DAG 上下文。

这里只测"对象造得出来吗、造出来对不对"，不碰文件也不碰网络。
"""

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


# 造一份基准请求，要改的字段用 kwargs 覆盖
# 注意它和 support.py 里那个同名函数不是一回事，这个只服务本文件
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


# 基准请求能造出来，顺便确认默认值和入参没被写坏
def test_valid_request():
    request = make_request()
    assert request.city == "镇江"
    assert request.travel_days == 2


# 结束日期早于开始日期要拒，日期顺序不能反
def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        make_request(
            start_date="2026-11-03",
            end_date="2026-11-01",
        )


# 11-01 到 11-03 实际是 3 天，写 travel_days=2 要拒
# 这是"两份冗余表达必须一致"的那条规则，前端最容易在这儿出错
def test_days_must_match_date_range():
    with pytest.raises(ValidationError):
        make_request(
            start_date="2026-11-01",
            end_date="2026-11-03",
            travel_days=2,
        )


# 换个城市直接拒，Day 1 只有镇江一份数据
def test_only_zhenjiang_supported():
    with pytest.raises(ValidationError):
        make_request(city="南京")


# 交通方式是白名单，"火箭"这种进不来
def test_unknown_transport_rejected():
    with pytest.raises(ValidationError):
        make_request(transportation="火箭")


# 自由文本上限 500 字，501 个字符要拒（防止把整篇文章塞进 prompt）
def test_free_text_is_bounded():
    with pytest.raises(ValidationError):
        make_request(free_text_input="x" * 501)


# 同一天的 DayPlanDraft 塞两次，日期重复要拒
# 注意只造了一个对象然后用两次，所以是"日期"重复而不是"景点"重复
def test_plan_draft_rejects_duplicate_dates():
    day = DayPlanDraft(
        date="2026-11-01",
        attraction_ids=["A001"],
        hotel_id="H001",
        meals=[MealChoice(type="breakfast", restaurant_id="R001")],
    )
    with pytest.raises(ValidationError):
        PlanDraft(days=[day, day])


# 正常路径：from_lines 自己算总额，账是平的，265 没超 300 的限额
# 异常路径：手写 total=0 和明细对不上，构造阶段就炸，不用等断言
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


# 三档严重度只影响一件事：warning 不挡路，blocking 挡路
# 校验器记一堆 warning 是正常的，只要没有 blocking 就该放行
def test_validation_result_blocking_semantics():
    result = ValidationResult()
    assert result.passed is True

    result.add("WARN", "只是提醒", severity="warning")
    assert result.passed is True

    result.add("BLOCK", "必须修复")
    assert result.passed is False
    assert result.has_blocking is True


# 三个类方法各自贴对状态标签（严格说这测的是 dag/context.py，不是 models）
def test_node_result_helpers():
    assert NodeResult.ok({"x": 1}).status == NodeStatus.ok
    assert NodeResult.degraded(error="weather timeout").status == NodeStatus.degraded
    assert NodeResult.failed("boom").status == NodeStatus.failed


# record 一次留一条 TraceEvent，时长原样存下来
# degraded 会被汇总成 True，错误信息也进 errors 字符串
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

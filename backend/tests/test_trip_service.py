"""服务层测试：缓存、幂等、限流、重算、并发。"""

import asyncio

import pytest

from app.infra.cache import MemoryCache
from app.services.trip_service import (
    PlanValidationError,
    RateLimitExceeded,
    TripNotFound,
    TripService,
)
from tests.support import FakePlanner, make_plan, make_request


# 造一个只依赖内存的服务实例：planner 可注入（默认 FakePlanner），
# 缓存走 MemoryCache，限流阈值可调
def make_service(planner=None, rate_limit=100):
    return TripService(
        planner=planner or FakePlanner(),
        cache=MemoryCache(),
        rate_limit_per_minute=rate_limit,
    )


# 正常规划：拿到结果 + trip_id，且快照里存了 request 和 plan。
# 快照是 /recalculate 的唯一数据源，所以这条其实在守重算的前提
def test_plan_returns_result_and_snapshot():
    service = make_service()
    outcome = asyncio.run(service.plan(make_request(), client_ip="test"))

    assert len(outcome.result.days) == 2
    assert outcome.trip_id.startswith("trip_")
    snapshot = service._load_snapshot(outcome.trip_id)
    assert snapshot is not None
    assert snapshot.request.city == "镇江"
    assert len(snapshot.plan.days) == 2


# 同参数请求两次：第二次必须命中计划缓存 —— planner 只调 1 次、
# trip_id 不变、cached=True
def test_plan_cache_avoids_second_planner_call():
    planner = FakePlanner()
    service = make_service(planner)
    request = make_request()

    first = asyncio.run(service.plan(request, client_ip="test"))
    second = asyncio.run(service.plan(request, client_ip="test"))

    assert planner.calls == 1
    assert first.trip_id == second.trip_id
    assert second.cached is True


# 和上一条的区别：这里显式传 idempotency_key。
# 幂等键优先于内容哈希，两条路径最终都指向同一个 trip_id
def test_idempotency_returns_same_trip():
    planner = FakePlanner()
    service = make_service(planner)
    request = make_request()

    first = asyncio.run(
        service.plan(request, idempotency_key="same-key", client_ip="test")
    )
    second = asyncio.run(
        service.plan(request, idempotency_key="same-key", client_ip="test")
    )

    assert planner.calls == 1
    assert first.trip_id == second.trip_id
    assert second.cached is True


# 阈值 2：第三次必须抛 RateLimitExceeded。
# 每次换开始日期是为了绕开计划缓存，否则根本走不到限流判断
def test_rate_limit_raises_after_limit():
    service = make_service(rate_limit=2)

    asyncio.run(service.plan(make_request(start="2026-11-01"), client_ip="1.1.1.1"))
    asyncio.run(service.plan(make_request(start="2026-11-03"), client_ip="1.1.1.1"))

    with pytest.raises(RateLimitExceeded):
        asyncio.run(
            service.plan(make_request(start="2026-11-05"), client_ip="1.1.1.1")
        )


# 重算不跑 DAG，只手工补三条 trace（validate/budget/render）——
# 这个断言正好解释了"重算为什么是毫秒级"：plan 和 load_dataset 被跳过了
def test_recalculate_updates_budget_and_trace():
    service = make_service()
    request = make_request()
    first = asyncio.run(service.plan(request, client_ip="test"))

    edited = make_plan(request, hotel_id="H001")  # H001 is more expensive than H002
    outcome = asyncio.run(service.recalculate(first.trip_id, edited))

    assert outcome.result.budget.total > first.result.budget.total
    assert outcome.result.budget.total == sum(
        line.amount for line in outcome.result.budget.lines
    )
    assert [event.node_id for event in outcome.result.trace] == [
        "validate",
        "budget",
        "render",
    ]


# 快照不存在 -> TripNotFound，API 层会把这条异常翻成 404
def test_recalculate_missing_trip():
    service = make_service()
    with pytest.raises(TripNotFound):
        asyncio.run(service.recalculate("trip_missing", None))


# 重算时的坏计划：抛 PlanValidationError 且带上 issues；
# 用例特意断言 DUPLICATE_ATTRACTION（同一天排了两次 A001）
def test_recalculate_rejects_invalid_plan():
    service = make_service()
    request = make_request()
    first = asyncio.run(service.plan(request, client_ip="test"))

    bad = make_plan(request)
    bad.days[0].attraction_ids = ["A001", "A001"]

    with pytest.raises(PlanValidationError) as exc_info:
        asyncio.run(service.recalculate(first.trip_id, bad))
    assert any(issue.code == "DUPLICATE_ATTRACTION" for issue in exc_info.value.issues)


# 两个请求并发跑（FakePlanner 各延迟 0.1s），断言各自结果里的日期不串。
# 守的是"一次请求一个 TripContext"，不是所有请求共用一份
def test_concurrent_requests_do_not_mix_contexts():
    planner = FakePlanner(delay=0.1)
    service = make_service(planner, rate_limit=100)
    first = make_request(start="2026-11-01")
    second = make_request(start="2026-12-01")

    async def run():
        return await asyncio.gather(
            service.plan(first, client_ip="a"),
            service.plan(second, client_ip="b"),
        )

    outcomes = asyncio.run(run())

    assert outcomes[0].result.request.start_date == "2026-11-01"
    assert outcomes[1].result.request.start_date == "2026-12-01"
    assert outcomes[0].result.days[0].date == "2026-11-01"
    assert outcomes[1].result.days[0].date == "2026-12-01"


# 健康检查只读进程内状态：不调 LLM、不建连接，
# 所以 FakePlanner 一次都没被调用，也能直接报 ok
def test_health_does_not_call_llm():
    service = make_service()
    health = service.health()
    assert health["status"] == "ok"
    assert health["cache"] == "memory"
    assert health["city"] == "镇江"

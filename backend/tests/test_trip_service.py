"""Trip service tests: cache, idempotency, rate limit, recalc, concurrency."""

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


def make_service(planner=None, rate_limit=100):
    return TripService(
        planner=planner or FakePlanner(),
        cache=MemoryCache(),
        rate_limit_per_minute=rate_limit,
    )


def test_plan_returns_result_and_snapshot():
    service = make_service()
    outcome = asyncio.run(service.plan(make_request(), client_ip="test"))

    assert len(outcome.result.days) == 2
    assert outcome.trip_id.startswith("trip_")
    snapshot = service._load_snapshot(outcome.trip_id)
    assert snapshot is not None
    assert snapshot.request.city == "镇江"
    assert len(snapshot.plan.days) == 2


def test_plan_cache_avoids_second_planner_call():
    planner = FakePlanner()
    service = make_service(planner)
    request = make_request()

    first = asyncio.run(service.plan(request, client_ip="test"))
    second = asyncio.run(service.plan(request, client_ip="test"))

    assert planner.calls == 1
    assert first.trip_id == second.trip_id
    assert second.cached is True


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


def test_rate_limit_raises_after_limit():
    service = make_service(rate_limit=2)

    asyncio.run(service.plan(make_request(start="2026-11-01"), client_ip="1.1.1.1"))
    asyncio.run(service.plan(make_request(start="2026-11-03"), client_ip="1.1.1.1"))

    with pytest.raises(RateLimitExceeded):
        asyncio.run(
            service.plan(make_request(start="2026-11-05"), client_ip="1.1.1.1")
        )


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


def test_recalculate_missing_trip():
    service = make_service()
    with pytest.raises(TripNotFound):
        asyncio.run(service.recalculate("trip_missing", None))


def test_recalculate_rejects_invalid_plan():
    service = make_service()
    request = make_request()
    first = asyncio.run(service.plan(request, client_ip="test"))

    bad = make_plan(request)
    bad.days[0].attraction_ids = ["A001", "A001"]

    with pytest.raises(PlanValidationError) as exc_info:
        asyncio.run(service.recalculate(first.trip_id, bad))
    assert any(issue.code == "DUPLICATE_ATTRACTION" for issue in exc_info.value.issues)


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


def test_health_does_not_call_llm():
    service = make_service()
    health = service.health()
    assert health["status"] == "ok"
    assert health["cache"] == "memory"
    assert health["city"] == "镇江"

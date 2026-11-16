"""API v1 接口测试：用 FakePlanner 替身，不联网、不需要 Redis。"""

from __future__ import annotations

import os

os.environ.setdefault("AMAP_API_KEY", "test-amap-key")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("LLM_MODEL_ID", "fake-model")

from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

from app.api.main import app  # noqa: E402
from app.infra.cache import MemoryCache  # noqa: E402
from app.services.trip_service import TripService, get_trip_service  # noqa: E402
from tests.support import FakePlanner, make_plan, make_request  # noqa: E402


# 造一个装好的 TripService：假 planner + 内存缓存，限流阈值可调
# （rate_limit=1 就是给后面那条 429 用例准备的）
def make_service(rate_limit: int = 100) -> tuple[TripService, FakePlanner]:
    planner = FakePlanner()
    service = TripService(
        planner=planner,
        cache=MemoryCache(),
        rate_limit_per_minute=rate_limit,
    )
    return service, planner


# 把 FastAPI 的 get_trip_service 换成刚造的服务，再包成 TestClient
# 注意 dependency_overrides 是全局的，所以每个用例结束都必须 clear
def make_client(service: TripService) -> TestClient:
    app.dependency_overrides[get_trip_service] = lambda: service
    return TestClient(app)


# 用例夹具：yield 出 client/service/planner 三件套，finally 里清掉依赖覆盖，
# 避免上一条用例的假服务漏到下一条
@pytest.fixture
def service_and_client():
    service, planner = make_service()
    client = make_client(service)
    try:
        with client:
            yield client, service, planner
    finally:
        app.dependency_overrides.clear()


# 主路径：POST 返回 200，且响应体里的 request_id 必须等于 X-Request-ID 响应头
# —— 这是中间件用 ContextVar 串起全链路之后，对外唯一看得见的证据
def test_create_trip_returns_plan_and_request_id(service_and_client):
    client, _, _ = service_and_client
    request = make_request()

    response = client.post(
        "/api/v1/trips",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["trip_id"].startswith("trip_")
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert len(body["data"]["days"]) == 2
    assert body["data"]["validation"]["passed"] is True


# 同一个 Idempotency-Key 打两次：trip_id 相同、第二次 cached=True、
# 且 planner 只被调 1 次 —— 说明幂等在进 DAG 之前就短路了
def test_idempotency_returns_same_trip(service_and_client):
    client, _, planner = service_and_client
    request = make_request()
    payload = request.model_dump(mode="json")

    first = client.post(
        "/api/v1/trips",
        json=payload,
        headers={"Idempotency-Key": "api-key-1"},
    )
    second = client.post(
        "/api/v1/trips",
        json=payload,
        headers={"Idempotency-Key": "api-key-1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trip_id"] == second.json()["trip_id"]
    assert second.json()["cached"] is True
    assert planner.calls == 1


# /api/v1/graph 返回的是 Mermaid 文本（不是图对象）；
# 断言里带 "load_dataset --> plan"，等于顺手验证了连线没断
def test_graph_endpoint(service_and_client):
    client, _, _ = service_and_client
    response = client.get("/api/v1/graph")
    assert response.status_code == 200
    mermaid = response.json()["mermaid"]
    assert "flowchart LR" in mermaid
    assert "load_dataset --> plan" in mermaid


# 根 /health 和 /api/v1/health 返回结构不同，但都必须活着、
# 都必须报出缓存后端名，且都不能碰 LLM
def test_health_endpoints(service_and_client):
    client, _, _ = service_and_client
    for path in ("/health", "/api/v1/health"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"healthy", "ok"}
        assert body["cache"] == "memory"


# 编辑重算：酒店换成更贵的 H001，总价必须涨，
# 同时 total 仍等于四条明细之和（预算恒等在这里再验一次）
def test_recalculate_updates_budget(service_and_client):
    client, _, _ = service_and_client
    request = make_request()
    created = client.post(
        "/api/v1/trips",
        json=request.model_dump(mode="json"),
    ).json()
    trip_id = created["trip_id"]
    original_total = created["data"]["budget"]["total"]

    edited = make_plan(request, hotel_id="H001")  # more expensive than H002
    response = client.post(
        f"/api/v1/trips/{trip_id}/recalculate",
        json={"plan": edited.model_dump(mode="json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["budget"]["total"] > original_total
    assert body["data"]["budget"]["total"] == sum(
        line["amount"] for line in body["data"]["budget"]["lines"]
    )


# 快照不存在 -> 404。这里 body 故意传 {}，用来确认
# "找不到 trip" 的判断发生在 "plan 参数缺失" 之前
def test_recalculate_missing_trip(service_and_client):
    client, _, _ = service_and_client
    response = client.post(
        "/api/v1/trips/trip_missing/recalculate",
        json={},
    )
    assert response.status_code == 404


# 重算路径的坏计划 -> 422 + PLAN_INVALID + issues 列表；
# 这是和主链路唯一的语义差异：主链路校验失败是 502，重算是 422
def test_recalculate_invalid_plan(service_and_client):
    client, _, _ = service_and_client
    request = make_request()
    created = client.post(
        "/api/v1/trips",
        json=request.model_dump(mode="json"),
    ).json()
    trip_id = created["trip_id"]

    bad = make_plan(request)
    bad.days[0].attraction_ids = ["A999", "A002"]
    response = client.post(
        f"/api/v1/trips/{trip_id}/recalculate",
        json={"plan": bad.model_dump(mode="json")},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "PLAN_INVALID"
    assert detail["issues"]


# 限流：阈值设 1，第二次换个日期（避免命中计划缓存）就必须 429，
# 且 Retry-After 要如实给出窗口剩余秒数
def test_rate_limit_returns_429():
    service, _ = make_service(rate_limit=1)
    client = make_client(service)
    try:
        with client:
            first = client.post(
                "/api/v1/trips",
                json=make_request(start="2026-11-01").model_dump(mode="json"),
            )
            second = client.post(
                "/api/v1/trips",
                json=make_request(start="2026-11-05").model_dump(mode="json"),
            )
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.headers["Retry-After"] == "60"
    finally:
        app.dependency_overrides.clear()

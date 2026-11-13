"""API v1 tests with a fake planner; no network and no Redis required."""

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


def make_service(rate_limit: int = 100) -> tuple[TripService, FakePlanner]:
    planner = FakePlanner()
    service = TripService(
        planner=planner,
        cache=MemoryCache(),
        rate_limit_per_minute=rate_limit,
    )
    return service, planner


def make_client(service: TripService) -> TestClient:
    app.dependency_overrides[get_trip_service] = lambda: service
    return TestClient(app)


@pytest.fixture
def service_and_client():
    service, planner = make_service()
    client = make_client(service)
    try:
        with client:
            yield client, service, planner
    finally:
        app.dependency_overrides.clear()


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


def test_graph_endpoint(service_and_client):
    client, _, _ = service_and_client
    response = client.get("/api/v1/graph")
    assert response.status_code == 200
    mermaid = response.json()["mermaid"]
    assert "flowchart LR" in mermaid
    assert "load_dataset --> plan" in mermaid


def test_health_endpoints(service_and_client):
    client, _, _ = service_and_client
    for path in ("/health", "/api/v1/health"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"healthy", "ok"}
        assert body["cache"] == "memory"


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


def test_recalculate_missing_trip(service_and_client):
    client, _, _ = service_and_client
    response = client.post(
        "/api/v1/trips/trip_missing/recalculate",
        json={},
    )
    assert response.status_code == 404


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

"""Versioned API: trips, graph and health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ...agents.planner import PlannerError
from ...domain.models import TripRequest
from ...infra.logging import get_logger, get_request_id
from ...llm.client import LLMConfigError
from ...services.trip_service import (
    PlanOutcome,
    PlanValidationError,
    RateLimitExceeded,
    TripNotFound,
    TripService,
    get_trip_service,
)
from .schemas import RecalculateRequest, TripPlanResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["v1"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _response(outcome: PlanOutcome, request_id: str) -> TripPlanResponse:
    result = outcome.result
    message = "旅行计划生成成功"
    if result.budget.over_budget:
        message = f"旅行计划生成成功，超出预算 {result.budget.over_budget} 元"
    if outcome.cached:
        message += "（命中缓存）"
    return TripPlanResponse(
        success=True,
        message=message,
        data=result,
        trip_id=outcome.trip_id,
        request_id=request_id,
        cached=outcome.cached,
    )


@router.post(
    "/trips",
    response_model=TripPlanResponse,
    summary="生成镇江旅行计划",
)
async def create_trip(
    payload: TripRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    service: TripService = Depends(get_trip_service),
) -> TripPlanResponse:
    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status_code=422, detail="Idempotency-Key 过长")

    try:
        outcome = await service.plan(
            payload,
            idempotency_key=idempotency_key,
            client_ip=_client_ip(http_request),
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": str(exc)},
            headers={"Retry-After": str(exc.retry_after_s)},
        ) from exc
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except PlannerError as exc:
        logger.warning("planner failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "PLANNER_FAILED", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - API boundary
        logger.exception("create_trip failed")
        raise HTTPException(
            status_code=502,
            detail={"code": "TRIP_FAILED", "message": str(exc)},
        ) from exc

    return _response(outcome, get_request_id())


@router.post(
    "/trips/{trip_id}/recalculate",
    response_model=TripPlanResponse,
    summary="编辑后重算预算",
)
async def recalculate_trip(
    trip_id: str,
    payload: RecalculateRequest,
    service: TripService = Depends(get_trip_service),
) -> TripPlanResponse:
    try:
        outcome = await service.recalculate(trip_id, payload.plan)
    except TripNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRIP_NOT_FOUND", "message": str(exc)},
        ) from exc
    except PlanValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PLAN_INVALID",
                "message": str(exc),
                "issues": [issue.model_dump() for issue in exc.issues],
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 - API boundary
        logger.exception("recalculate failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "RECALCULATE_FAILED", "message": str(exc)},
        ) from exc

    return _response(outcome, get_request_id())


@router.get("/graph", summary="获取 DAG 的 Mermaid 图")
async def get_graph(
    service: TripService = Depends(get_trip_service),
) -> dict[str, str]:
    return {"mermaid": service.graph_mermaid()}


@router.get("/health", summary="v1 健康检查")
async def health(
    service: TripService = Depends(get_trip_service),
) -> dict:
    return service.health()

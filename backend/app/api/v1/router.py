"""v1 接口：生成行程、重算、取 DAG 图、健康检查。

这一层很薄：取 IP、把 service 抛的异常翻译成 HTTP 状态码、拼响应壳。
业务逻辑全在 services/trip_service.py，这里不做任何计算。
"""

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


# 从请求里取客户端 IP，给限流当 key
# 注意取的是 X-Forwarded-For 的第一个值，而这个头客户端能自己伪造，公网部署下等于没限流
def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


# 把 PlanOutcome 包成统一响应壳：success + message + data + trip_id
# message 会自动拼上"超预算多少"和"命中缓存"，前端直接显示
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


# 生成行程：整条链路唯一的"花钱"入口
# 幂等、限流、缓存都在 service.plan 里，这里只负责把异常翻译成状态码
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
    # 只查长度不查字符集：这个值会拼进缓存 key，太长会把 key 撑爆
    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status_code=422, detail="Idempotency-Key 过长")

    try:
        outcome = await service.plan(
            payload,
            idempotency_key=idempotency_key,
            client_ip=_client_ip(http_request),
        )
    except RateLimitExceeded as exc:
        # 429 带 Retry-After，前端可以据此倒计时
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": str(exc)},
            headers={"Retry-After": str(exc.retry_after_s)},
        ) from exc
    except LLMConfigError as exc:
        # 503：服务端自己没配好（缺 key），和"模型调失败"要分开
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except PlannerError as exc:
        # 502：上游模型出问题
        logger.warning("planner failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "PLANNER_FAILED", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - API boundary
        # 兜底：把异常文本原样透传给客户端，理论上存在泄露内部信息的风险
        logger.exception("create_trip failed")
        raise HTTPException(
            status_code=502,
            detail={"code": "TRIP_FAILED", "message": str(exc)},
        ) from exc

    return _response(outcome, get_request_id())


# 用户改完行程后重算：不调模型，只重跑校验 + 预算 + 渲染
# 快照过期或查不到就是 404，校验不过把 issues 一起返回给前端
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
        # 422 带上全部 issues 明细，前端可以逐条标红
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


# 把 DAG 导成 Mermaid 文本，前端拿去画流程图
@router.get("/graph", summary="获取 DAG 的 Mermaid 图")
async def get_graph(
    service: TripService = Depends(get_trip_service),
) -> dict[str, str]:
    return {"mermaid": service.graph_mermaid()}


# v1 健康检查：缓存后端、模型配置、图里有几个节点
@router.get("/health", summary="v1 健康检查")
async def health(
    service: TripService = Depends(get_trip_service),
) -> dict:
    return service.health()

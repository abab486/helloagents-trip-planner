"""Trip application service: cache, idempotency, rate limit and recalculation.

This layer owns request-level concerns so the DAG stays pure:
    - plan cache / idempotency / rate limit
    - trip snapshot storage (Redis or memory)
    - recalculate endpoint logic
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from ..agents.planner import PlannerAgent
from ..dag.context import NodeResult, TripContext, TripResult
from ..dag.llm_pipeline import (
    build_llm_graph,
    run_llm_pipeline_context_async,
)
from ..dag.walking_skeleton import budget_plan, render_trip, validate_plan
from ..domain.models import Facts, PlanDraft, TripRequest, ValidationIssue
from ..infra.cache import Cache, create_cache, hash_payload
from ..infra.logging import get_logger
from ..llm.client import LLMConfigError, create_llm_client

logger = get_logger(__name__)


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_s: int = 60) -> None:
        super().__init__("请求过于频繁，请稍后再试")
        self.retry_after_s = retry_after_s


class TripNotFound(RuntimeError):
    pass


class PlanValidationError(RuntimeError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("行程校验失败")
        self.issues = issues


class TripSnapshot(BaseModel):
    trip_id: str
    request: TripRequest
    facts: Facts
    plan: PlanDraft
    created_at: float = Field(default_factory=time.time)


@dataclass
class PlanOutcome:
    result: TripResult
    trip_id: str
    cached: bool = False


class TripService:
    def __init__(
        self,
        *,
        planner: PlannerAgent | None = None,
        cache: Cache | None = None,
        rate_limit_per_minute: int | None = None,
        plan_ttl_s: int = 3600,
        idem_ttl_s: int = 600,
    ) -> None:
        self._planner = planner
        self._planner_lock = threading.Lock()
        self.cache = cache or create_cache()
        self.rate_limit_per_minute = (
            rate_limit_per_minute
            if rate_limit_per_minute is not None
            else int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
        )
        self.plan_ttl_s = plan_ttl_s
        self.idem_ttl_s = idem_ttl_s

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def plan(
        self,
        request: TripRequest,
        *,
        idempotency_key: str | None = None,
        client_ip: str = "unknown",
    ) -> PlanOutcome:
        request_hash = hash_payload(request.model_dump(mode="json"))

        if idempotency_key:
            cached = self._cache_get(f"idem:{idempotency_key}")
            if cached and cached.get("request_hash") == request_hash:
                try:
                    result = TripResult.model_validate(cached["result"])
                    return PlanOutcome(
                        result=result,
                        trip_id=cached["trip_id"],
                        cached=True,
                    )
                except (KeyError, ValidationError):
                    logger.warning("幂等缓存损坏，忽略: %s", idempotency_key)

        self._check_rate_limit(client_ip)

        plan_key = f"plan:{request_hash}"
        cached_plan = self._cache_get(plan_key)
        if cached_plan:
            snapshot = self._load_snapshot(cached_plan.get("trip_id", ""))
            if snapshot is not None:
                try:
                    result = TripResult.model_validate(cached_plan["result"])
                    if idempotency_key:
                        self._remember_idempotency(
                            idempotency_key, request_hash, snapshot.trip_id, result
                        )
                    logger.info("plan cache hit: %s", request_hash)
                    return PlanOutcome(
                        result=result,
                        trip_id=snapshot.trip_id,
                        cached=True,
                    )
                except (KeyError, ValidationError):
                    logger.warning("计划缓存损坏，忽略: %s", request_hash)

        planner = self._get_planner()
        result, context = await run_llm_pipeline_context_async(request, planner)
        if context.facts is None or context.plan is None:
            raise RuntimeError("规划结果缺少 facts / plan")

        trip_id = f"trip_{uuid4().hex[:12]}"
        snapshot = TripSnapshot(
            trip_id=trip_id,
            request=request,
            facts=context.facts,
            plan=context.plan,
        )
        self._save_snapshot(snapshot)

        result_payload = result.model_dump(mode="json")
        self._cache_set(
            plan_key,
            {"trip_id": trip_id, "result": result_payload},
            self.plan_ttl_s,
        )
        if idempotency_key:
            self._remember_idempotency(
                idempotency_key, request_hash, trip_id, result
            )

        logger.info(
            "plan created: trip_id=%s days=%s budget=%s tokens=%s",
            trip_id,
            len(result.days),
            result.budget.total,
            sum(event.meta.get("total_tokens", 0) for event in result.trace),
        )
        return PlanOutcome(result=result, trip_id=trip_id, cached=False)

    async def recalculate(
        self,
        trip_id: str,
        plan_override: PlanDraft | None = None,
    ) -> PlanOutcome:
        snapshot = self._load_snapshot(trip_id)
        if snapshot is None:
            raise TripNotFound(f"行程不存在或已过期: {trip_id}")

        plan = plan_override or snapshot.plan
        validation = validate_plan(plan, snapshot.facts, snapshot.request)
        if not validation.passed:
            raise PlanValidationError(validation.issues)

        context = TripContext(
            request=snapshot.request,
            facts=snapshot.facts,
            plan=plan,
            validation=validation,
        )

        started = time.perf_counter()
        context.record(
            "validate",
            NodeResult.ok({"issues": len(validation.issues)}),
            (time.perf_counter() - started) * 1000,
        )

        started = time.perf_counter()
        context.budget = budget_plan(plan, snapshot.facts, snapshot.request)
        context.record(
            "budget",
            NodeResult.ok(context.budget.summary()),
            (time.perf_counter() - started) * 1000,
            over_budget=context.budget.over_budget,
        )

        started = time.perf_counter()
        result = render_trip(context)
        context.record(
            "render",
            NodeResult.ok({"days": len(result.days)}),
            (time.perf_counter() - started) * 1000,
        )
        result.trace = list(context.trace)
        result.degraded = context.degraded

        snapshot.plan = plan
        self._save_snapshot(snapshot)
        self._cache_set(
            f"plan:{hash_payload(snapshot.request.model_dump(mode='json'))}",
            {
                "trip_id": trip_id,
                "result": result.model_dump(mode="json"),
            },
            self.plan_ttl_s,
        )

        logger.info(
            "plan recalculated: trip_id=%s budget=%s over=%s",
            trip_id,
            result.budget.total,
            result.budget.over_budget,
        )
        return PlanOutcome(result=result, trip_id=trip_id, cached=False)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "cache": self.cache.backend,
            "llm_configured": bool(
                os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            ),
            "model": os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL") or "",
            "city": "镇江",
            "graph_nodes": len(build_llm_graph(None)),
        }

    def graph_mermaid(self) -> str:
        return build_llm_graph(None).to_mermaid()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get_planner(self) -> PlannerAgent:
        if self._planner is not None:
            return self._planner
        with self._planner_lock:
            if self._planner is None:
                try:
                    self._planner = PlannerAgent(create_llm_client())
                except LLMConfigError:
                    raise
        return self._planner

    def _check_rate_limit(self, client_ip: str) -> None:
        if self.rate_limit_per_minute <= 0:
            return
        window = int(time.time() // 60)
        key = f"rate:{client_ip}:{window}"
        try:
            count = self.cache.incr(key, 60)
        except Exception as exc:  # noqa: BLE001 - never fail open due to cache
            logger.warning("限流缓存不可用，跳过限流: %s", exc)
            return
        if count > self.rate_limit_per_minute:
            raise RateLimitExceeded()

    def _load_snapshot(self, trip_id: str) -> TripSnapshot | None:
        if not trip_id:
            return None
        data = self._cache_get(f"trip:{trip_id}")
        if not data:
            return None
        try:
            return TripSnapshot.model_validate(data)
        except ValidationError:
            logger.warning("行程快照损坏: %s", trip_id)
            return None

    def _save_snapshot(self, snapshot: TripSnapshot) -> None:
        self._cache_set(
            f"trip:{snapshot.trip_id}",
            snapshot.model_dump(mode="json"),
            self.plan_ttl_s,
        )

    def _remember_idempotency(
        self,
        key: str,
        request_hash: str,
        trip_id: str,
        result: TripResult,
    ) -> None:
        self._cache_set(
            f"idem:{key}",
            {
                "request_hash": request_hash,
                "trip_id": trip_id,
                "result": result.model_dump(mode="json"),
            },
            self.idem_ttl_s,
        )

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            return self.cache.get_json(key)
        except Exception as exc:  # noqa: BLE001 - cache is optional
            logger.warning("缓存读取失败 %s: %s", key, exc)
            return None

    def _cache_set(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        try:
            self.cache.set_json(key, value, ttl_s)
        except Exception as exc:  # noqa: BLE001 - cache is optional
            logger.warning("缓存写入失败 %s: %s", key, exc)


_service: TripService | None = None
_service_lock = threading.Lock()


def get_trip_service() -> TripService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = TripService()
    return _service

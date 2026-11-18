"""行程应用服务：缓存、幂等、限流和重算。

这一层专门管"请求级"的脏活，让 DAG 保持纯粹：
    - 计划缓存 / 幂等 / 限流
    - 行程快照的存取（Redis 或内存）
    - 重算接口的逻辑
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


# 限流被挡住时抛它，顺手把"多少秒后再试"带给 router 塞进 Retry-After
class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_s: int = 60) -> None:
        super().__init__("请求过于频繁，请稍后再试")
        self.retry_after_s = retry_after_s


# 快照查不到或已过期，重算接口拿它报 404
class TripNotFound(RuntimeError):
    pass


# 校验没过，把 issues 一起抛，router 原样塞进 422 的 detail
class PlanValidationError(RuntimeError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("行程校验失败")
        self.issues = issues


# 快照：把 request + facts + plan 三样冻在一起
# 必须存 facts —— 重算要的是"原计划那版数据"，现读 CSV 会和原结果对不上
class TripSnapshot(BaseModel):
    trip_id: str
    request: TripRequest
    facts: Facts
    plan: PlanDraft
    created_at: float = Field(default_factory=time.time)


# 一次 plan 的返回：结果 + trip_id + 这次是不是命中缓存
@dataclass
class PlanOutcome:
    result: TripResult
    trip_id: str
    cached: bool = False


# 行程服务的门面，对外只有 plan / recalculate / health / graph
# 依赖全从构造函数注入，测试里能塞 FakePlanner 和 MemoryCache，不碰真 LLM
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
        # 只防 PlannerAgent 被初始化两次，不限制并发量（这项目没有并发隔离）
        self._planner_lock = threading.Lock()
        # 没配 REDIS_URL 就退化成进程内字典；多副本部署时限流会按进程各算一份
        self.cache = cache or create_cache()
        self.rate_limit_per_minute = (
            rate_limit_per_minute
            if rate_limit_per_minute is not None
            else int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
        )
        self.plan_ttl_s = plan_ttl_s
        self.idem_ttl_s = idem_ttl_s

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    # 主流程：幂等 → 限流 → 计划缓存 → 跑 DAG → 写三层缓存
    # 只有最后一步花钱，前面三道命中就直接返回
    async def plan(
        self,
        request: TripRequest,
        *,
        idempotency_key: str | None = None,
        client_ip: str = "unknown",
    ) -> PlanOutcome:
        # 请求体哈希：同参数才认缓存，参数变了就得重算
        request_hash = hash_payload(request.model_dump(mode="json"))

        # 幂等：光有 key 不够，哈希也得一致 —— 客户端可能把同一个 key 用在不同请求上
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

        # 限流放在幂等之后：已经算过的请求重放，不该再吃配额
        self._check_rate_limit(client_ip)

        # 同参数的请求 1 小时内直接复用，这是省钱的主力
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

        # 到这儿才真调模型，也是整条链路唯一超过 1 秒的地方
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

    # 编辑后重算：不调模型，只把 validate / budget / render 再跑一遍
    # facts 取自快照而不是现读 CSV，保证跟原计划用同一版数据
    async def recalculate(
        self,
        trip_id: str,
        plan_override: PlanDraft | None = None,
    ) -> PlanOutcome:
        snapshot = self._load_snapshot(trip_id)
        if snapshot is None:
            raise TripNotFound(f"行程不存在或已过期: {trip_id}")

        # 不传新计划就按原计划重算，等于只刷新一次预算
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

        # 注意：started 打在 validate_plan 跑完之后，所以这条 trace 恒为 0.00ms
        # 下面 budget / render 两条的 started 在调用之前，是对的
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

    # 给运维看的：用哪个缓存后端、模型配没配、图里几个节点
    # 注意 graph_nodes 是每次调用都重建一遍图数出来的，健康检查频繁调有点浪费
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

    # 把 DAG 导成 Mermaid 文本，前端拿去渲染成图（同样是每次重建图）
    def graph_mermaid(self) -> str:
        return build_llm_graph(None).to_mermaid()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    # 懒加载 PlannerAgent：第一次调用才建 LLM 客户端，没配 key 就抛 LLMConfigError
    # 双检锁是 Java 那套习惯，Python 里其实一把普通锁就够
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

    # 按 IP + 分钟固定窗口计数，key 里带分钟数，天然按窗口过期
    # 缓存挂了直接放行（可用性优先），所以 Redis 故障时等于没限流
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

    # 读快照：反序列化失败当"过期"处理，不让脏数据冒到上层
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

    # 存快照，TTL 跟计划缓存一致；重算接口就靠它拿 facts
    def _save_snapshot(self, snapshot: TripSnapshot) -> None:
        self._cache_set(
            f"trip:{snapshot.trip_id}",
            snapshot.model_dump(mode="json"),
            self.plan_ttl_s,
        )

    # 写幂等键，同时把请求体哈希记下来，下次来要比对
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

    # 缓存读的统一入口：出错只记日志不抛，缓存本来就可有可无
    def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            return self.cache.get_json(key)
        except Exception as exc:  # noqa: BLE001 - cache is optional
            logger.warning("缓存读取失败 %s: %s", key, exc)
            return None

    # 同上，写失败也不影响这次请求的结果
    def _cache_set(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        try:
            self.cache.set_json(key, value, ttl_s)
        except Exception as exc:  # noqa: BLE001 - cache is optional
            logger.warning("缓存写入失败 %s: %s", key, exc)


# 模块级单例：全进程共用一个 TripService（也就共用一个 PlannerAgent）
_service: TripService | None = None
_service_lock = threading.Lock()


# 拿单例，双检锁防止并发首次调用建出两个
def get_trip_service() -> TripService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = TripService()
    return _service

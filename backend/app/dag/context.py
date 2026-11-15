"""DAG 执行上下文、节点回执与 Trace 事件。

Day 1 的骨架链路和 Day 2 的真实执行器共用这套契约。放在一处，
将来换执行器时节点代码不用改。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import (
    AttractionCandidate,
    BudgetReport,
    DayPlanDraft,
    Facts,
    Narrative,
    PlanDraft,
    TripRequest,
    ValidationResult,
)

"""
 DAG 的“记忆体”:NodeResult 规定工人怎么交差,TripContext 规定数据放哪儿,TraceEvent 规定过程怎么留痕。
 明确声明了“无跨请求状态、无全局历史”，这是相对旧链路 ContextBuilder 的对照。
 留了 5 个空字段给未来的 Critic/Weather/降级路径，还没有实现。
 """

# DAG状态 正常 / 降级 / 失败 / 跳过
# 执行器贴，前端显示
class NodeStatus(str, Enum):
    ok = "ok"
    degraded = "degraded"
    failed = "failed"
    skipped = "skipped"

# 回执单：状态 + 一句结果 + 错误信息
# 每个节点函数的返回值
class NodeResult(BaseModel):
    """每个 DAG 节点统一返回的回执单。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: NodeStatus
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, **meta: Any) -> "NodeResult":
        return cls(status=NodeStatus.ok, data=data, meta=meta)

    @classmethod
    def degraded(
        cls, data: Any = None, error: str = "", **meta: Any
    ) -> "NodeResult":
        return cls(
            status=NodeStatus.degraded,
            data=data,
            error=error or None,
            meta=meta,
        )

    @classmethod
    def failed(cls, error: str, **meta: Any) -> "NodeResult":
        return cls(status=NodeStatus.failed, error=error, meta=meta)

# 谁、多久、什么状态、错没错
# 前端时间轴、评测报告
class TraceEvent(BaseModel):
    node_id: str
    status: NodeStatus
    duration_ms: float = 0.0
    cache: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

# TripContext 是每次请求的上下文，节点之间通过修改同一个 TripContext 实例传递数据
# 真实数据载体
class TripContext(BaseModel):
    """单次请求的状态。没有全局 Agent 历史，没有跨请求状态。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: TripRequest
    facts: Facts | None = None
    candidates: list[AttractionCandidate] = Field(default_factory=list)
    plan: PlanDraft | None = None
    validation: ValidationResult | None = None
    budget: BudgetReport | None = None
    narrative: Narrative | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    degraded: bool = False
    errors: list[str] = Field(default_factory=list)

    def record(
        self,
        node_id: str,
        result: NodeResult,
        duration_ms: float = 0.0,
        **meta: Any,
    ) -> TraceEvent:
        event = TraceEvent(
            node_id=node_id,
            status=result.status,
            duration_ms=round(duration_ms, 2),
            error=result.error,
            meta={**result.meta, **meta},
        )
        self.trace.append(event)
        if result.status == NodeStatus.degraded:
            self.degraded = True
            if result.error:
                self.errors.append(result.error)
        elif result.status == NodeStatus.failed:
            self.errors.append(result.error or f"{node_id} failed")
        return event

    def mark_degraded(self, reason: str) -> None:
        self.degraded = True
        if reason:
            self.errors.append(reason)

    def selected_attraction_ids(self) -> list[str]:
        if self.plan is None:
            return []
        return [
            attraction_id
            for day in self.plan.days
            for attraction_id in day.attraction_ids
        ]


# ---------------------------------------------------------------------------
# 给前端看的成品模型（Day 1 骨架用，也是未来 API 响应体的形状）
# ---------------------------------------------------------------------------
# 存在的唯一理由：PlanDraft 里只有 ID，而用户要看名字/门票/坐标，
# 展开这一步必然产出新对象，所以 View 不是冗余
class AttractionView(BaseModel):
    id: str
    name: str
    area: str
    ticket_price: int
    duration_min: int
    description: str = ""
    must_see: bool = False
    indoor: bool = False
    walking_level: int = 2
    lat: float = 0.0
    lng: float = 0.0


class HotelView(BaseModel):
    id: str
    name: str
    tier: str
    area: str
    price_per_night: int
    lat: float = 0.0
    lng: float = 0.0


class MealView(BaseModel):
    type: str
    restaurant_id: str
    name: str
    avg_price: int
    area: str


class WeatherView(BaseModel):
    date: str
    day_weather: str = ""
    night_weather: str = ""
    day_temp: int = 0
    night_temp: int = 0
    precipitation_prob: int = 0
    source: str = ""


class DayView(BaseModel):
    date: str
    day_index: int
    theme: str = ""
    transport_mode: str = "公共交通"
    attractions: list[AttractionView] = Field(default_factory=list)
    hotel: HotelView | None = None
    meals: list[MealView] = Field(default_factory=list)


class TripResult(BaseModel):
    request: TripRequest
    days: list[DayView]
    budget: BudgetReport
    validation: ValidationResult
    weather: list[WeatherView] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)

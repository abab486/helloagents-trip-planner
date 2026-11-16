"""LLM 规划器：只从结构化事实里挑 ID，绝不自己写事实和价格。

它刻意做得很薄、没有状态：一份 system prompt、一份结构化 payload、只回 JSON，
遇到非法 JSON / 未知 ID 就返工一次。

完整的硬约束校验仍然归 Validator 节点；这里只提前挡掉明显的错，给模型一次
自己改对的机会。
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from ..domain.models import Facts, PlanDraft, TripRequest
from ..llm.client import LLMClient

PROMPT_VERSION = "planner_v1"

SYSTEM_PROMPT = """你是镇江行程规划器。

你的唯一任务：从给定的候选 ID 中，选择每天要去的景点、酒店和餐厅，并输出严格 JSON。

**硬约束（代码会校验，违反会要求你重试）：**
1. 只能使用候选列表中出现过的 ID；不允许编造 ID 或名称。
2. days 数量必须等于 request.travel_days，日期必须从 start_date 开始连续。
3. 每天安排 2–3 个景点，优先覆盖 must_see=true 的景点。
4. 不要安排 closed_days 包含当天星期几的景点（0=周一，6=周日）。
5. 每天必须包含 breakfast / lunch / dinner 三餐，餐厅必须提供对应餐型。
6. 每天必须有一个酒店 ID，且来自候选酒店。
7. 不要输出名称、地址、价格、坐标、营业时间；这些字段由代码填充。
8. 不要输出 Markdown、解释、注释、代码围栏；只输出一个 JSON 对象。

**输出结构：**
{
  "days": [
    {
      "date": "YYYY-MM-DD",
      "attraction_ids": ["A001", "A002"],
      "hotel_id": "H001",
      "meals": [
        {"type": "breakfast", "restaurant_id": "R001"},
        {"type": "lunch", "restaurant_id": "R002"},
        {"type": "dinner", "restaurant_id": "R003"}
      ],
      "transport_mode": "公共交通",
      "theme": "历史文化"
    }
  ],
  "notes": ["可选：给规划器的说明"]
}
"""


"""
类/函数	         承诺	              兑现情况
SYSTEM_PROMPT	8 条硬约束	           5 条被代码检查，3 条只写在文字里
PlannerError	带上下文的结构化失败	三个字段外部零引用，router 的 except PlannerError 是死代码
PlannerResult	可观测的成功回执	     7/9 字段被 trace 消费，latency_ms/raw_content 无人读
extract_json	从废话里取 JSON	         三层降级有效；无长度限制、无截断恢复
PlannerAgent.plan	失败重试一次	      路径 B 有效，路径 A 近乎无效；tokens/latency 口径不一致
_build_payload	给模型刚好够的信息	      塞了重复 schema 和不被 prompt 提及的 must_see_ids
_validate_ids	早筛 7 条	             6 条扎实，三餐那条漏重复餐型
"""
# 规划彻底失败时抛的异常，试了几次、最后一次错在哪、模型最后说了什么
class PlannerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_error: str = "",
        raw_content: str = "",
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.raw_content = raw_content

# 成功的回执 一份计划 + 七个成本/溯源指标
class PlannerResult(BaseModel):
    plan: PlanDraft
    attempts: int
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    prompt_version: str = PROMPT_VERSION
    raw_content: str = ""

# 从 LLM 响应中提取 JSON
def extract_json(text: str) -> dict[str, Any]:
    """从模型回复里挖出第一个 JSON 对象（先剥掉 ``` 围栏和前后废话）。"""
    if not text or not text.strip():
        raise ValueError("LLM 返回为空")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("响应中没有 JSON 对象") from None
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("LLM 输出的 JSON 顶层必须是对象")
    return data

# 无状态的“提问机”——组装 payload、发请求、验收、不行就带着错误重发一次、还不行就抛异常。
# 不记历史、不写事实
class PlannerAgent:
    """无状态的 LLM 规划器，失败时只允许返工一次。"""

    def __init__(
        self,
        llm: LLMClient,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_retries: int = 1,
    ) -> None:
        self.llm = llm
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    # 最多问两次，第一次问错了，第二次带着错误提示再问一次
    def plan(self, request: TripRequest, facts: Facts) -> PlannerResult:
        payload = self._build_payload(request, facts)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ]

        attempts = self.max_retries + 1
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        last_error: Exception | None = None
        last_raw = ""

        for attempt in range(1, attempts + 1):
            try:
                response = self.llm.complete_json(
                    messages,
                    model=self.model,
                    temperature=self.temperature,
                    timeout=self.timeout,
                )
            except Exception as exc:  # noqa: BLE001 - 网络/服务商故障，节点失败要被兜住
                last_error = exc
                if attempt < attempts:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"上一次调用失败：{exc}。"
                                "请重新输出严格 JSON，不要解释。"
                            ),
                        }
                    )
                    continue
                break

            prompt_tokens += response.prompt_tokens
            completion_tokens += response.completion_tokens
            total_tokens += response.total_tokens
            last_raw = response.content

            try:
                data = extract_json(response.content)
                plan = PlanDraft.model_validate(data)
                self._validate_ids(plan, request, facts)
                return PlannerResult(
                    plan=plan,
                    attempts=attempt,
                    model=response.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=response.latency_ms,
                    prompt_version=PROMPT_VERSION,
                    raw_content=response.content,
                )
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if attempt < attempts:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": response.content[:4000],
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"上一次输出不合法：{exc}。"
                                "请严格按输出结构重新生成，只输出 JSON。"
                                "只能使用候选 ID，不要编造。"
                            ),
                        }
                    )

        raise PlannerError(
            f"Planner 在 {attempts} 次尝试后仍然失败: {last_error}",
            attempts=attempts,
            last_error=str(last_error or ""),
            raw_content=last_raw,
        )

    # ------------------------------------------------------------------
    # payload 组装 / 提前校验
    # ------------------------------------------------------------------
    # 把“用户填的表 + 全城候选”压成一个大 JSON 当 user 消息
    @staticmethod
    def _build_payload(request: TripRequest, facts: Facts) -> dict[str, Any]:
        return {
            "task": "为镇江生成一份可执行的旅行计划",
            "request": request.model_dump(mode="json"),
            "candidate_attractions": [item.brief() for item in facts.attractions],
            "candidate_hotels": [item.brief() for item in facts.hotels],
            "candidate_restaurants": [item.brief() for item in facts.restaurants],
            "weather": [item.brief() for item in facts.weather],
            "constraints": {
                "days": request.travel_days,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "attractions_per_day": "2-3",
                "meals_per_day": ["breakfast", "lunch", "dinner"],
                "must_cover": "优先安排 must_see=true 的景点",
                "max_daily_minutes": 540,
                "budget_limit": request.budget_limit,
                "party": request.party,
                "pace": request.pace,
            },
            "output_schema": PlanDraft.model_json_schema(),
        }
    
    # 一份“格式检查清单”，只查“引用对不对、形状对不对”，不查“合不合理”
    """
    序	行	查什么	怎么查的巧妙处
1	L247–253	日期数量 + 连续	两边都转成 toordinal()，列表直接 !=，一行同时查了“数量”和“顺序”
2	L262	每天 2–3 个景点	not 2 <= len(...) <= 3
3	L266	景点 ID 存在	集合成员测试
4	L268	全局不重复	seen_attractions 跨天累积
5	L271	当天不闭馆	weekday in closed_days（0=周一，和 CSV 对齐）
6	L276	酒店 ID 存在	集合成员测试
7	L280–289	三餐齐全 + 餐型匹配	集合相等 + restaurant.serves()
    """
    @staticmethod
    def _validate_ids(plan: PlanDraft, request: TripRequest, facts: Facts) -> None:
        expected_dates = [
            date.fromisoformat(request.start_date).toordinal() + index
            for index in range(request.travel_days)
        ]
        actual_dates = [date.fromisoformat(day.date).toordinal() for day in plan.days]
        if actual_dates != expected_dates:
            raise ValueError("days 的日期必须从 start_date 开始连续且数量等于 travel_days")

        attraction_ids = {item.id for item in facts.attractions}
        hotel_ids = {item.id for item in facts.hotels}
        restaurants = {item.id: item for item in facts.restaurants}
        attractions = {item.id: item for item in facts.attractions}
        seen_attractions: set[str] = set()

        for day_index, day in enumerate(plan.days, start=1):
            if not 2 <= len(day.attraction_ids) <= 3:
                raise ValueError(f"第 {day_index} 天必须安排 2–3 个景点")
            weekday = date.fromisoformat(day.date).weekday()
            for attraction_id in day.attraction_ids:
                if attraction_id not in attraction_ids:
                    raise ValueError(f"未知景点 ID: {attraction_id}")
                if attraction_id in seen_attractions:
                    raise ValueError(f"景点重复: {attraction_id}")
                seen_attractions.add(attraction_id)
                if weekday in attractions[attraction_id].closed_days:
                    raise ValueError(
                        f"{attraction_id} 在 {day.date} 闭馆，请换一个景点"
                    )

            if day.hotel_id not in hotel_ids:
                raise ValueError(f"未知酒店 ID: {day.hotel_id}")

            meal_types = {meal.type for meal in day.meals}
            if meal_types != {"breakfast", "lunch", "dinner"}:
                raise ValueError(f"第 {day_index} 天必须包含早中晚三餐")
            for meal in day.meals:
                restaurant = restaurants.get(meal.restaurant_id)
                if restaurant is None:
                    raise ValueError(f"未知餐厅 ID: {meal.restaurant_id}")
                if not restaurant.serves(meal.type):
                    raise ValueError(
                        f"餐厅 {restaurant.id} 不提供 {meal.type}"
                    )

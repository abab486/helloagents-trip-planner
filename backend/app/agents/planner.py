"""LLM Planner: choose IDs from typed facts, never write facts or prices.

The planner is deliberately a thin, stateless component:
    - one system prompt
    - one structured payload
    - JSON-only output
    - one repair retry on invalid JSON / unknown IDs

Full hard-constraint validation still belongs to the Validator node. This
class only rejects obvious errors early so the LLM gets a chance to repair.
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


def extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response."""
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


class PlannerAgent:
    """Stateless LLM planner with one repair retry."""

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
            except Exception as exc:  # noqa: BLE001 - network/provider failure
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
    # Payload / early checks
    # ------------------------------------------------------------------
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

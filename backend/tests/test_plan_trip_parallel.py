"""plan_trip 并行调度测试

用假的 Agent 模拟耗时，验证：
1. 三个子 Agent 是并发执行的（总耗时接近单个，而不是累加）；
2. 单个 Agent 失败/超时不会拖垮整个请求。
"""

import asyncio
import json
import time

from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.models.budget import PriceHit
from app.models.schemas import TripRequest
from app.services.budget_calculator import BudgetCalculator
from app.services.context_builder import ContextBuilder

PLAN_JSON = json.dumps(
    {
        "city": "镇江",
        "start_date": "2026-10-19",
        "end_date": "2026-10-21",
        "days": [],
        "overall_suggestions": "ok",
    },
    ensure_ascii=False,
)


class FakeRepository:
    """所有查询都不命中，走计划内值 / 默认值"""

    def get_attraction(self, city, name):
        return None

    def get_hotel(self, city, name, tier=""):
        return None

    def get_meal(self, city, meal_type):
        return None

    def get_transport(self, city, mode):
        return None


class SlowAgent:
    def __init__(self, response, delay=0.0, error=None):
        self.response = response
        self.delay = delay
        self.error = error
        self.calls = 0

    def clear_history(self):
        pass

    def run(self, query):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.response


class CaptureAgent:
    def __init__(self, response):
        self.response = response
        self.last_query = None

    def clear_history(self):
        pass

    def run(self, query):
        self.last_query = query
        return self.response


def make_request():
    return TripRequest(
        city="镇江",
        start_date="2026-10-19",
        end_date="2026-10-21",
        travel_days=3,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
    )


def make_planner(attraction, weather, hotel, planner_response=PLAN_JSON):
    planner = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    planner.context_builder = ContextBuilder(max_token_budget=4000)
    planner.budget_calculator = BudgetCalculator(FakeRepository())
    planner.attraction_agent = attraction
    planner.weather_agent = weather
    planner.hotel_agent = hotel
    planner.planner_agent = CaptureAgent(planner_response)
    return planner


def test_three_agents_run_in_parallel():
    delay = 0.3
    planner = make_planner(
        SlowAgent("**金山寺**（金山路62号）", delay=delay),
        SlowAgent("| 日期 | 天气 | 温度 |", delay=delay),
        SlowAgent("**格林豪泰** 200-300元", delay=delay),
    )

    started = time.perf_counter()
    plan = asyncio.run(planner.plan_trip(make_request()))
    elapsed = time.perf_counter() - started

    # 串行需要 0.9s 以上，并行应接近 0.3s
    assert elapsed < 0.75
    assert plan.city == "镇江"


def test_agent_failure_is_isolated():
    planner = make_planner(
        SlowAgent("**金山寺**（金山路62号）"),
        SlowAgent("", error=RuntimeError("天气服务不可用")),
        SlowAgent("**格林豪泰** 200-300元"),
    )

    plan = asyncio.run(planner.plan_trip(make_request()))

    # 一个 Agent 失败，整体仍然返回计划
    assert plan.city == "镇江"
    assert planner.attraction_agent.calls == 1
    assert planner.weather_agent.calls == 1
    assert planner.hotel_agent.calls == 1


def test_planner_receives_all_three_results():
    planner = make_planner(
        SlowAgent("**金山寺**（金山路62号）"),
        SlowAgent("| 日期 | 天气 | 温度 |\n| 2026-10-19 | 晴 | 20℃ |"),
        SlowAgent("**格林豪泰** 200-300元"),
    )

    asyncio.run(planner.plan_trip(make_request()))
    prompt = planner.planner_agent.last_query

    assert "金山寺" in prompt
    assert "20℃" in prompt
    assert "格林豪泰" in prompt

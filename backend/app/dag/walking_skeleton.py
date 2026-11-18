"""Day 1 的走路骨架，现在改由 Day 2 的 DAG 方式执行。

流水线：
    load_dataset -> fake_plan -> validate -> budget -> render

依然不碰 LLM、MySQL、Redis。保留它能跑，是为 Day 3 用真实 LLM 替换
fake_plan 之前先留一条回归基线：

    python -m app.dag.walking_skeleton --days 2 --budget 800
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

from ..data.loader import load_facts
from ..domain.models import (
    AttractionCandidate,
    BudgetLine,
    BudgetReport,
    DayPlanDraft,
    Facts,
    HotelCandidate,
    MealChoice,
    PlanDraft,
    RestaurantCandidate,
    TripRequest,
    ValidationResult,
)
from .context import (
    AttractionView,
    DayView,
    HotelView,
    MealView,
    NodeResult,
    NodeStatus,
    TripContext,
    TripResult,
    WeatherView,
)
from .executor import DAGExecutor
from .graph import Graph


"""
TRANSPORT_DAILY = {"公共交通": 30, "步行": 0, "打车": 80, "自驾": 100, "混合": 40} —— 一个人一天在城里移动的固定开销，不是按距离算的。

_season_for_month：3-5 春、6-8 夏、9-11 秋、其余冬。镇江在江苏，这个划分没问题。

_eligible(景点, 当天, 请求) —— 三道门槛

今天是不是闭馆日（周一博物馆关门）
这个季节开不开（CSV 里 5 个景点标的是 春|秋，夏天冬天不该去）
同行有老人时，步行强度 3 级以上的不去（walking_level >= 3 排除）
_choose_hotel：先按用户选的住宿档位（经济型/舒适型/豪华/民宿）筛，筛不到就用全部；然后取最便宜的那家，价格相同按 ID 排。

_choose_restaurant：三层优先级 —— 能提供这顿饭的 → 尽量同区域 → 尽量今天没吃过 → 取最便宜。used 是按天重置的，所以同一家餐厅可以在第二天再出现。
"""
# 常量
MEAL_TYPES = ("breakfast", "lunch", "dinner")
MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
TIER_BY_ACCOMMODATION = {
    "经济型酒店": "经济型",
    "舒适型酒店": "舒适型",
    "豪华酒店": "豪华型",
    "民宿": "民宿",
}
TRANSPORT_DAILY = {"公共交通": 30, "步行": 0, "打车": 80, "自驾": 100, "混合": 40}
DEFAULT_HOTEL_PRICE = 200
DEFAULT_MEAL_PRICE = {"breakfast": 30, "lunch": 50, "dinner": 70}
MAX_DAILY_MINUTES = 540


# 日期列表
def _date_list(start_date: str, days: int) -> list[date]:
    start = date.fromisoformat(start_date)
    return [start + timedelta(days=index) for index in range(days)]

# 季节判断
def _season_for_month(month: int) -> str:
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"

# 默认交通模式
def _transport_mode(value: str) -> str:
    return value if value in TRANSPORT_DAILY else "公共交通"

# 景点是否可选
def _eligible(attraction: AttractionCandidate, current: date, request: TripRequest) -> bool:
    if current.weekday() in attraction.closed_days:
        return False
    if "全年" not in attraction.season and _season_for_month(current.month) not in attraction.season:
        return False
    if request.party == "elderly" and attraction.walking_level >= 3:
        return False
    return True

# 选择酒店
def _choose_hotel(request: TripRequest, facts: Facts) -> HotelCandidate:
    tier = TIER_BY_ACCOMMODATION.get(request.accommodation, "")
    pool = [hotel for hotel in facts.hotels if hotel.tier == tier] or facts.hotels
    if not pool:
        raise RuntimeError("没有可用酒店数据")
    return min(pool, key=lambda hotel: (hotel.price_per_night, hotel.id))

# 选择餐厅
def _choose_restaurant(
    meal_type: str,
    area: str,
    facts: Facts,
    used: set[str],
) -> RestaurantCandidate:
    options = [item for item in facts.restaurants if item.serves(meal_type)]
    if not options:
        raise RuntimeError(f"没有可用于 {meal_type} 的餐厅数据")
    same_area = [item for item in options if item.area == area]
    pool = same_area or options
    fresh = [item for item in pool if item.id not in used]
    pool = fresh or pool
    chosen = min(pool, key=lambda item: (item.avg_price, item.id))
    used.add(chosen.id)
    return chosen

# 不借用LLM 凑出一套合法行程，规则规划器,基线非产品
def fake_plan(request: TripRequest, facts: Facts) -> PlanDraft:
    """确定性规划器，只用到真实 LLM Planner 接进来之前。

    它不试图成为一个好规划器，只证明 ID 契约成立：
    计划里只有 ID，名称/门票等事实由后续节点展开。
    """
    dates = _date_list(request.start_date, request.travel_days)
    hotel = _choose_hotel(request, facts)
    selected: set[str] = set()
    days: list[DayPlanDraft] = []

    for index, current in enumerate(dates):
        pool = [
            attraction
            for attraction in facts.attractions
            if attraction.id not in selected
            and _eligible(attraction, current, request)
        ]
        if not pool:
            raise RuntimeError(f"{current.isoformat()} 没有可用景点")

        # 用户点名的必去 ID 优先，其次是城市级推荐，最后按 ID 字典序。
        # 策展的 ID 顺序（A001 金山寺 -> A002 西津渡）比按区域名字排序更合理，
        # 能保证骨架从经典集群开始。
        pool.sort(
            key=lambda item: (
                0 if item.id in request.must_see_ids
                else (1 if item.must_see else 2),
                item.id,
            )
        )
        anchor = pool[0]
        same_area = [
            item for item in pool if item.id != anchor.id and item.area == anchor.area
        ]
        second_pool = same_area or [item for item in pool if item.id != anchor.id]
        if not second_pool:
            raise RuntimeError(f"{current.isoformat()} 无法安排第二个景点")
        second = second_pool[0]

        selected.add(anchor.id)
        selected.add(second.id)

        meals: list[MealChoice] = []
        used_today: set[str] = set()
        for meal_type in MEAL_TYPES:
            area = hotel.area if meal_type == "breakfast" else anchor.area
            restaurant = _choose_restaurant(meal_type, area, facts, used_today)
            meals.append(MealChoice(type=meal_type, restaurant_id=restaurant.id))

        theme = request.preferences[0] if request.preferences else "综合"
        days.append(
            DayPlanDraft(
                date=current.isoformat(),
                attraction_ids=[anchor.id, second.id],
                hotel_id=hotel.id,
                meals=meals,
                transport_mode=_transport_mode(request.transportation),
                theme=theme,
            )
        )

    return PlanDraft(
        days=days,
        notes=["Day 1 walking skeleton: deterministic fake planner, no LLM."],
    )


"""
阻塞级（blocking，会让整单失败）9 条：

code	查什么
DAY_COUNT_MISMATCH	计划天数 ≠ 请求天数
DATE_MISMATCH	第 N 天的日期不对（日期必须严格连续）
EMPTY_DAY	某天一个景点都没有
UNKNOWN_ATTRACTION	景点 ID 在 CSV 里不存在（幻觉的第一道网）
CLOSED_DAY	那天这个景点闭馆
UNKNOWN_HOTEL	酒店 ID 不存在
MISSING_MEAL	早/午/晚缺了哪顿
UNKNOWN_RESTAURANT	餐厅 ID 不存在
RESTAURANT_MEAL_TYPE	这家餐厅不卖这顿饭（比如早餐店被安排成晚餐）
DUPLICATE_ATTRACTION	同一趟行程里同一个景点出现两次

警告级（warning，只提示不拦截）4 条：
code	查什么
DAY_PACE	每天景点数不在 2–3 之间
DAY_TOO_LONG	预计超过 540 分钟（9 小时）
MUST_SEE_COVERAGE	必去景点覆盖数 < min(2, 天数)
MISSING_WEATHER	天气没覆盖出行日期
「预计时长」怎么算的：60 分钟（吃饭休息）+ 各景点时长之和 + 每多一个景点加 20 分钟（路上）。是个粗糙但诚实的估算。

passed 的判据在 ValidationResult 里：只要有一条 blocking 就不通过，warning 再多都算通过。所以“超预算”和“太累”这类事永远不会拦住用户，只会显示成黄条。
"""
# 规则校验器，分blocking/warning
def validate_plan(
    plan: PlanDraft,
    facts: Facts,
    request: TripRequest,
) -> ValidationResult:
    result = ValidationResult()
    expected_dates = [item.isoformat() for item in _date_list(request.start_date, request.travel_days)]

    if len(plan.days) != request.travel_days:
        result.add(
            "DAY_COUNT_MISMATCH",
            f"计划天数 {len(plan.days)} != 请求天数 {request.travel_days}",
            target="plan.days",
        )

    all_attraction_ids: list[str] = []
    selected_must_see: set[str] = set()

    for index, day in enumerate(plan.days):
        target = f"days[{index}]"
        if index < len(expected_dates) and day.date != expected_dates[index]:
            result.add(
                "DATE_MISMATCH",
                f"第 {index + 1} 天日期 {day.date} != {expected_dates[index]}",
                target=f"{target}.date",
            )

        if len(day.attraction_ids) < 1:
            result.add("EMPTY_DAY", "每天至少需要 1 个景点", target=target)
        elif not 2 <= len(day.attraction_ids) <= 3:
            result.add(
                "DAY_PACE",
                f"每天安排了 {len(day.attraction_ids)} 个景点，建议 2–3 个",
                severity="warning",
                target=target,
            )

        daily_minutes = 60  # meals / rest
        for attraction_id in day.attraction_ids:
            all_attraction_ids.append(attraction_id)
            attraction = facts.attraction_by_id(attraction_id)
            if attraction is None:
                result.add(
                    "UNKNOWN_ATTRACTION",
                    f"景点 ID 不存在: {attraction_id}",
                    target=f"{target}.attraction_ids",
                )
                continue
            if not attraction.is_open_on(date.fromisoformat(day.date).weekday()):
                result.add(
                    "CLOSED_DAY",
                    f"{attraction.name} 在 {day.date} 闭馆",
                    target=f"{target}.{attraction_id}",
                )
            if attraction.must_see:
                selected_must_see.add(attraction.id)
            daily_minutes += attraction.duration_min

        if len(day.attraction_ids) > 1:
            daily_minutes += (len(day.attraction_ids) - 1) * 20
        if daily_minutes > MAX_DAILY_MINUTES:
            result.add(
                "DAY_TOO_LONG",
                f"第 {index + 1} 天预计 {daily_minutes} 分钟，超过 {MAX_DAILY_MINUTES}",
                severity="warning",
                target=target,
            )

        if facts.hotel_by_id(day.hotel_id) is None:
            result.add(
                "UNKNOWN_HOTEL",
                f"酒店 ID 不存在: {day.hotel_id}",
                target=f"{target}.hotel_id",
            )

        meal_types = {meal.type for meal in day.meals}
        missing_meals = set(MEAL_TYPES) - meal_types
        if missing_meals:
            result.add(
                "MISSING_MEAL",
                f"缺少餐次: {sorted(missing_meals)}",
                target=f"{target}.meals",
            )
        for meal in day.meals:
            restaurant = facts.restaurant_by_id(meal.restaurant_id)
            if restaurant is None:
                result.add(
                    "UNKNOWN_RESTAURANT",
                    f"餐厅 ID 不存在: {meal.restaurant_id}",
                    target=f"{target}.meals",
                )
            elif not restaurant.serves(meal.type):
                result.add(
                    "RESTAURANT_MEAL_TYPE",
                    f"{restaurant.name} 不提供 {meal.type}",
                    target=f"{target}.meals",
                )

    if len(all_attraction_ids) != len(set(all_attraction_ids)):
        result.add(
            "DUPLICATE_ATTRACTION",
            "同一行程重复安排了景点",
            target="plan.days",
        )

    required_must_see = min(2, request.travel_days)
    if len(selected_must_see) < required_must_see:
        result.add(
            "MUST_SEE_COVERAGE",
            f"必去景点覆盖 {len(selected_must_see)} < {required_must_see}",
            severity="warning",
            target="plan.days",
        )

    if facts.weather:
        weather_dates = {item.date for item in facts.weather}
        missing_weather = set(expected_dates) - weather_dates
        if missing_weather:
            result.add(
                "MISSING_WEATHER",
                f"天气未覆盖: {sorted(missing_weather)}",
                severity="warning",
                target="facts.weather",
            )

    return result

"""
budget_plan —— 四项钱
项	    怎么算	                                              source
景点	每个景点一张票，ticket_price                           直接取 CSV	csv
酒店	nights = max(天数-1, 1) 晚，每晚取“当天那家酒店”的价格	 csv / default
餐饮	每顿取餐厅 avg_price，找不到餐厅用默认价（早30/午50/晚70）	csv / default
交通	TRANSPORT_DAILY[模式] × 天数，每天固定	                default
"""
# 算钱
def budget_plan(
    plan: PlanDraft,
    facts: Facts,
    request: TripRequest,
) -> BudgetReport:
    lines: list[BudgetLine] = []

    for day in plan.days:
        for attraction_id in day.attraction_ids:
            attraction = facts.attraction_by_id(attraction_id)
            if attraction is None:
                continue
            lines.append(
                BudgetLine(
                    category="attraction",
                    ref_id=attraction.id,
                    name=attraction.name,
                    amount=attraction.ticket_price,
                    source="csv",
                    detail=f"{attraction.price_note or '参考价'} / {day.date}",
                )
            )

    nights = max(request.travel_days - 1, 1)
    hotel_ids = [day.hotel_id for day in plan.days]
    for index in range(nights):
        hotel_id = hotel_ids[min(index, len(hotel_ids) - 1)]
        hotel = facts.hotel_by_id(hotel_id)
        if hotel is None:
            lines.append(
                BudgetLine(
                    category="hotel",
                    ref_id=hotel_id,
                    name="默认酒店",
                    amount=DEFAULT_HOTEL_PRICE,
                    source="default",
                    detail=f"第 {index + 1} 晚",
                )
            )
            continue
        lines.append(
            BudgetLine(
                category="hotel",
                ref_id=hotel.id,
                name=hotel.name,
                amount=hotel.price_per_night,
                source="csv",
                detail=f"第 {index + 1} 晚 / {hotel.tier}",
            )
        )

    for day in plan.days:
        for meal in day.meals:
            restaurant = facts.restaurant_by_id(meal.restaurant_id)
            if restaurant is None:
                lines.append(
                    BudgetLine(
                        category="meal",
                        ref_id=meal.restaurant_id,
                        name=MEAL_LABELS.get(meal.type, meal.type),
                        amount=DEFAULT_MEAL_PRICE.get(meal.type, 50),
                        source="default",
                        detail=day.date,
                    )
                )
                continue
            lines.append(
                BudgetLine(
                    category="meal",
                    ref_id=restaurant.id,
                    name=f"{MEAL_LABELS[meal.type]}·{restaurant.name}",
                    amount=restaurant.avg_price,
                    source="csv",
                    detail=day.date,
                )
            )

    mode = _transport_mode(request.transportation)
    daily = TRANSPORT_DAILY.get(mode, 40)
    for day in plan.days:
        lines.append(
            BudgetLine(
                category="transport",
                ref_id=mode,
                name=f"{mode}日预算",
                amount=daily,
                source="default",
                detail=day.date,
            )
        )

    return BudgetReport.from_lines(lines, budget_limit=request.budget_limit)

# 渲染行程 render_trip：ID 展开成名字、门票、坐标
def render_trip(context: TripContext) -> TripResult:
    if context.facts is None or context.plan is None or context.budget is None:
        raise RuntimeError("render_trip 需要 facts / plan / budget")
    if context.validation is None:
        raise RuntimeError("render_trip 需要 validation")

    facts = context.facts
    days: list[DayView] = []
    for index, day in enumerate(context.plan.days):
        attractions: list[AttractionView] = []
        for attraction_id in day.attraction_ids:
            attraction = facts.attraction_by_id(attraction_id)
            if attraction is None:
                continue
            attractions.append(
                AttractionView(
                    id=attraction.id,
                    name=attraction.name,
                    area=attraction.area,
                    ticket_price=attraction.ticket_price,
                    duration_min=attraction.duration_min,
                    description=attraction.description,
                    must_see=attraction.must_see,
                    indoor=attraction.indoor,
                    walking_level=attraction.walking_level,
                    lat=attraction.lat,
                    lng=attraction.lng,
                )
            )

        hotel = facts.hotel_by_id(day.hotel_id)
        hotel_view = (
            HotelView(
                id=hotel.id,
                name=hotel.name,
                tier=hotel.tier,
                area=hotel.area,
                price_per_night=hotel.price_per_night,
                lat=hotel.lat,
                lng=hotel.lng,
            )
            if hotel
            else None
        )

        meals: list[MealView] = []
        for meal in day.meals:
            restaurant = facts.restaurant_by_id(meal.restaurant_id)
            if restaurant is None:
                continue
            meals.append(
                MealView(
                    type=meal.type,
                    restaurant_id=restaurant.id,
                    name=restaurant.name,
                    avg_price=restaurant.avg_price,
                    area=restaurant.area,
                )
            )

        days.append(
            DayView(
                date=day.date,
                day_index=index,
                theme=day.theme,
                transport_mode=day.transport_mode,
                attractions=attractions,
                hotel=hotel_view,
                meals=meals,
            )
        )

    return TripResult(
        request=context.request,
        days=days,
        budget=context.budget,
        validation=context.validation,
        weather=[
            WeatherView(
                date=item.date,
                day_weather=item.day_weather,
                night_weather=item.night_weather,
                day_temp=item.day_temp,
                night_temp=item.night_temp,
                precipitation_prob=item.precipitation_prob,
                source=item.source,
            )
            for item in facts.weather
        ],
        trace=list(context.trace),
        degraded=context.degraded,
        notes=list(context.plan.notes),
    )


# ---------------------------------------------------------------------------
# Day 2: the same five steps, now as DAG nodes
# ---------------------------------------------------------------------------

# DAG节点包装+建图+同步入口+CLI
def load_dataset_node(context: TripContext) -> NodeResult:
    facts = load_facts(
        context.request.start_date,
        context.request.travel_days,
    )
    context.facts = facts
    context.candidates = list(facts.attractions)
    return NodeResult.ok(facts.summary(), data_version=facts.data_version)


def fake_plan_node(context: TripContext) -> NodeResult:
    if context.facts is None:
        raise RuntimeError("fake_plan 需要 facts")
    plan = fake_plan(context.request, context.facts)
    context.plan = plan
    return NodeResult.ok({"days": len(plan.days)})


def validate_node(context: TripContext) -> NodeResult:
    if context.facts is None or context.plan is None:
        raise RuntimeError("validate 需要 facts / plan")
    validation = validate_plan(context.plan, context.facts, context.request)
    context.validation = validation
    if not validation.passed:
        return NodeResult.failed(
            "计划校验失败: "
            + "; ".join(issue.message for issue in validation.issues),
            blocking=True,
            issues=len(validation.issues),
        )
    return NodeResult.ok(
        {"issues": len(validation.issues)},
        blocking=False,
    )


def budget_node(context: TripContext) -> NodeResult:
    if context.facts is None or context.plan is None:
        raise RuntimeError("budget 需要 facts / plan")
    budget = budget_plan(context.plan, context.facts, context.request)
    context.budget = budget
    return NodeResult.ok(budget.summary(), over_budget=budget.over_budget)


def render_node(context: TripContext) -> NodeResult:
    return NodeResult.ok(render_trip(context))

# vbuild_llm_graph() 的差别只有一行：中间那个节点是 fake_plan_node 还是 make_llm_plan_node(planner)。
# 换一个零件，用于评测
def build_skeleton_graph() -> Graph:
    """把 Day 1 的流水线表达成一张 DAG。

    五个节点全是 required；可选工具节点和条件分支是 Day 3 以后的事。
    """
    graph = Graph()
    graph.add("load_dataset", load_dataset_node)
    graph.add("fake_plan", fake_plan_node, depends_on=("load_dataset",))
    graph.add("validate", validate_node, depends_on=("fake_plan",))
    graph.add("budget", budget_node, depends_on=("validate",))
    graph.add("render", render_node, depends_on=("budget",))
    return graph

# 同步入口 跑图、失败时收集 event.error 抛 ValueError、把完整 trace 补回 TripResult
def run_walking_skeleton(request: TripRequest) -> TripResult:
    context = TripContext(request=request)
    execution = asyncio.run(DAGExecutor().run(build_skeleton_graph(), context))

    if not execution.success:
        errors = [
            event.error
            for event in execution.trace
            if event.status == NodeStatus.failed and event.error
        ]
        raise ValueError(
            "DAG 执行失败: " + ("; ".join(errors) if errors else str(execution.failed))
        )

    result = execution.outputs.get("render")
    if not isinstance(result, TripResult):
        raise RuntimeError("render 节点没有返回 TripResult")

    # render 节点是在执行器记录它自己那条 trace 之前跑的，
    # 所以这里用执行完的完整 trace 覆盖一遍，补上缺的那一条。
    result.trace = list(execution.trace)
    result.degraded = context.degraded
    return result


def build_request_from_args(args: argparse.Namespace) -> TripRequest:
    start = date.fromisoformat(args.start_date)
    end = start + timedelta(days=args.days - 1)
    return TripRequest(
        city="镇江",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        travel_days=args.days,
        transportation=args.transportation,
        accommodation=args.accommodation,
        preferences=args.preferences,
        free_text_input=args.free_text,
        budget_limit=args.budget,
        party=args.party,
        pace=args.pace,
        must_see_ids=args.must_see,
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Day 1 walking skeleton: deterministic fake planner, no LLM."
    )
    parser.add_argument("--days", type=int, default=2, help="行程天数 1–7")
    parser.add_argument("--budget", type=int, default=800, help="预算上限，元")
    parser.add_argument(
        "--start-date",
        default=date.today().isoformat(),
        help="开始日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--preferences",
        nargs="*",
        default=["历史文化"],
        help="偏好标签，如 历史文化 美食",
    )
    parser.add_argument(
        "--transportation",
        default="公共交通",
        choices=["公共交通", "步行", "打车", "自驾", "混合"],
    )
    parser.add_argument(
        "--accommodation",
        default="经济型酒店",
        help="经济型酒店/舒适型酒店/豪华酒店/民宿",
    )
    parser.add_argument(
        "--party",
        default="solo",
        choices=["solo", "couple", "family", "elderly"],
    )
    parser.add_argument(
        "--pace",
        default="normal",
        choices=["relaxed", "normal", "packed"],
    )
    parser.add_argument("--free-text", default="", help="额外要求")
    parser.add_argument(
        "--must-see",
        nargs="*",
        default=[],
        help="必去景点 ID，如 A001 A002",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        request = build_request_from_args(args)
        result = run_walking_skeleton(request)
    except Exception as exc:  # noqa: BLE001 - CLI should print a useful error
        print(f"[FAIL] {exc}")
        return 2
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

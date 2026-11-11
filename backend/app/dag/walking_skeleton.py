"""Day 1 walking skeleton, now executed as a Day 2 DAG.

Pipeline:
    load_dataset -> fake_plan -> validate -> budget -> render

Still no LLM, MySQL or Redis. Keeping this script runnable gives us a
regression baseline before Day 3 swaps fake_plan for a real LLM planner:

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
)
from .executor import DAGExecutor
from .graph import Graph

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


def _date_list(start_date: str, days: int) -> list[date]:
    start = date.fromisoformat(start_date)
    return [start + timedelta(days=index) for index in range(days)]


def _season_for_month(month: int) -> str:
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


def _transport_mode(value: str) -> str:
    return value if value in TRANSPORT_DAILY else "公共交通"


def _eligible(attraction: AttractionCandidate, current: date, request: TripRequest) -> bool:
    if current.weekday() in attraction.closed_days:
        return False
    if "全年" not in attraction.season and _season_for_month(current.month) not in attraction.season:
        return False
    if request.party == "elderly" and attraction.walking_level >= 3:
        return False
    return True


def _choose_hotel(request: TripRequest, facts: Facts) -> HotelCandidate:
    tier = TIER_BY_ACCOMMODATION.get(request.accommodation, "")
    pool = [hotel for hotel in facts.hotels if hotel.tier == tier] or facts.hotels
    if not pool:
        raise RuntimeError("没有可用酒店数据")
    return min(pool, key=lambda hotel: (hotel.price_per_night, hotel.id))


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


def fake_plan(request: TripRequest, facts: Facts) -> PlanDraft:
    """Deterministic planner used only until the LLM Planner is wired in.

    It does not try to be a good planner. It proves the ID contract:
    the plan contains only IDs; facts/prices are expanded later.
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

        # Curated ID order (A001, A002, ...) beats lexicographic area order,
        # so the skeleton starts with the classic 金山寺 -> 西津渡 cluster.
        pool.sort(key=lambda item: (0 if item.must_see else 1, item.id))
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
        trace=list(context.trace),
        degraded=context.degraded,
        notes=list(context.plan.notes),
    )


# ---------------------------------------------------------------------------
# Day 2: the same five steps, now as DAG nodes
# ---------------------------------------------------------------------------
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


def build_skeleton_graph() -> Graph:
    """The Day 1 pipeline expressed as a DAG.

    Every node is required; Day 3+ will add optional tool nodes/conditions.
    """
    graph = Graph()
    graph.add("load_dataset", load_dataset_node)
    graph.add("fake_plan", fake_plan_node, depends_on=("load_dataset",))
    graph.add("validate", validate_node, depends_on=("fake_plan",))
    graph.add("budget", budget_node, depends_on=("validate",))
    graph.add("render", render_node, depends_on=("budget",))
    return graph


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

    # The render node runs before the executor records its own trace event;
    # attach the complete trace after execution.
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

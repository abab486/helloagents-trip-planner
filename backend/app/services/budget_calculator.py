"""预算计算器

不再信任 LLM 写的 budget，而是用价格库 + 确定性规则重算四项金额，
并把结果回写到每个明细（景点门票、酒店、餐饮），保证「明细相加 = 汇总」。

兜底顺序（每一项都是）：
    价格库命中 → 计划内的模型估算值 → 默认值
"""

from typing import Optional

from ..db.repository import PriceRepository
from ..models.budget import BudgetItem, BudgetReport
from ..models.schemas import Budget, TripPlan, TripRequest
from .price_normalizer import (
    normalize_attraction_name,
    normalize_city,
    normalize_transport_mode,
)

DEFAULT_HOTEL_PRICE = 200
DEFAULT_MEAL_PRICE = {"breakfast": 30, "lunch": 50, "dinner": 70}
DEFAULT_MEAL_FALLBACK = 50
DEFAULT_TRANSPORT_PRICE = {"公共交通": 30, "打车": 80, "自驾": 100, "步行": 0}
DEFAULT_TRANSPORT_FALLBACK = 40


class BudgetCalculator:
    """按确定性规则重算旅行预算"""

    def __init__(self, repository: Optional[PriceRepository] = None):
        self.repository = repository if repository is not None else PriceRepository()

    def apply(self, plan: TripPlan, request: TripRequest) -> BudgetReport:
        """重算四项金额，回写明细，并覆盖 plan.budget"""
        report = BudgetReport()
        city = normalize_city(request.city)

        self._apply_attractions(plan, city, report)
        self._apply_hotels(plan, request, city, report)
        self._apply_meals(plan, city, report)
        self._apply_transport(plan, request, city, report)

        plan.budget = Budget(
            total_attractions=report.total_by("attraction"),
            total_hotels=report.total_by("hotel"),
            total_meals=report.total_by("meal"),
            total_transportation=report.total_by("transport"),
            total=report.total,
        )

        # 预算上限：有上限时计算超出金额，供前端提示
        plan.budget_limit = request.budget_limit
        if request.budget_limit is not None and request.budget_limit > 0:
            plan.over_budget = max(report.total - request.budget_limit, 0)
        else:
            plan.over_budget = 0

        return report

    # ------------------------------------------------------------------
    def _apply_attractions(self, plan: TripPlan, city: str, report: BudgetReport) -> None:
        for day in plan.days:
            for attraction in day.attractions:
                normalized = normalize_attraction_name(attraction.name, city)
                hit = self.repository.get_attraction(city, normalized)

                if hit is not None:
                    price, source = hit.value, hit.source
                elif attraction.ticket_price > 0:
                    price, source = attraction.ticket_price, "plan"
                else:
                    price, source = 0, "default"

                attraction.ticket_price = price
                report.items.append(
                    BudgetItem("attraction", attraction.name, price, source)
                )

    # ------------------------------------------------------------------
    def _apply_hotels(
        self,
        plan: TripPlan,
        request: TripRequest,
        city: str,
        report: BudgetReport,
    ) -> None:
        # 3 天行程住 2 晚：按「天数 - 1」计价，至少 1 晚
        nights = max(request.travel_days - 1, 1)
        hotels = [day.hotel for day in plan.days if day.hotel is not None]

        for index in range(nights):
            hotel = hotels[min(index, len(hotels) - 1)] if hotels else None

            if hotel is None:
                report.items.append(
                    BudgetItem("hotel", "（默认酒店价格）", DEFAULT_HOTEL_PRICE, "default")
                )
                continue

            tier = hotel.type or request.accommodation
            hit = self.repository.get_hotel(city, hotel.name, tier)

            if hit is not None:
                price, source = hit.value, hit.source
            elif hotel.estimated_cost > 0:
                price, source = hotel.estimated_cost, "plan"
            else:
                price, source = DEFAULT_HOTEL_PRICE, "default"

            hotel.estimated_cost = price
            report.items.append(BudgetItem("hotel", hotel.name, price, source))

    # ------------------------------------------------------------------
    def _apply_meals(self, plan: TripPlan, city: str, report: BudgetReport) -> None:
        for day in plan.days:
            for meal in day.meals:
                meal_type = (meal.type or "").strip().lower()
                hit = self.repository.get_meal(city, meal_type)

                if hit is not None:
                    price, source = hit.value, hit.source
                elif meal.estimated_cost > 0:
                    price, source = meal.estimated_cost, "plan"
                else:
                    price = DEFAULT_MEAL_PRICE.get(meal_type, DEFAULT_MEAL_FALLBACK)
                    source = "default"

                meal.estimated_cost = price
                report.items.append(BudgetItem("meal", meal.name, price, source))

    # ------------------------------------------------------------------
    def _apply_transport(
        self,
        plan: TripPlan,
        request: TripRequest,
        city: str,
        report: BudgetReport,
    ) -> None:
        mode = normalize_transport_mode(request.transportation)
        hit = self.repository.get_transport(city, mode)

        if hit is not None:
            per_day, source = hit.value, hit.source
        else:
            per_day = DEFAULT_TRANSPORT_PRICE.get(mode, DEFAULT_TRANSPORT_FALLBACK)
            source = "default"

        days = max(request.travel_days, 1)
        report.items.append(BudgetItem("transport", mode, per_day * days, source))

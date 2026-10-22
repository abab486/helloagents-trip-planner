"""BudgetCalculator 单元测试（使用假仓储，不依赖数据库）"""

from app.models.budget import PriceHit
from app.models.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripRequest
from app.services.budget_calculator import BudgetCalculator


class FakeRepository:
    """按名称返回预设命中结果"""

    def __init__(self, attractions=None, hotels=None, meals=None, transports=None):
        self.attractions = attractions or {}
        self.hotels = hotels or {}
        self.meals = meals or {}
        self.transports = transports or {}

    def get_attraction(self, city, name):
        return self.attractions.get(name)

    def get_hotel(self, city, name, tier=""):
        return self.hotels.get(name)

    def get_meal(self, city, meal_type):
        return self.meals.get(meal_type)

    def get_transport(self, city, mode):
        return self.transports.get(mode)


def make_request(days=3, transportation="公共交通", budget_limit=None):
    return TripRequest(
        city="镇江市",
        start_date="2026-10-19",
        end_date="2026-10-21",
        travel_days=days,
        transportation=transportation,
        accommodation="经济型酒店",
        preferences=["历史文化"],
        budget_limit=budget_limit,
    )


def make_plan(days=3, ticket_price=50, hotel_cost=300, meal_costs=(20, 40, 60)):
    location = Location(longitude=119.4, latitude=32.2)
    day_plans = []
    for index in range(days):
        day_plans.append(
            DayPlan(
                date=f"2026-10-{19 + index:02d}",
                day_index=index,
                description="d",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=Hotel(
                    name="格林豪泰(镇江中央大街大润发店)",
                    type="经济型",
                    estimated_cost=hotel_cost,
                ),
                attractions=[
                    Attraction(
                        name="金山寺(金山公园内)",
                        address="",
                        location=location,
                        visit_duration=120,
                        description="x",
                        ticket_price=ticket_price,
                    )
                ],
                meals=[
                    Meal(type="breakfast", name="早餐", estimated_cost=meal_costs[0]),
                    Meal(type="lunch", name="午餐", estimated_cost=meal_costs[1]),
                    Meal(type="dinner", name="晚餐", estimated_cost=meal_costs[2]),
                ],
            )
        )
    return TripPlan(
        city="镇江市",
        start_date="2026-10-19",
        end_date="2026-10-21",
        days=day_plans,
        overall_suggestions="x",
    )


def test_all_hit_uses_database():
    repo = FakeRepository(
        attractions={"金山寺": PriceHit(65, "db", "金山寺")},
        hotels={"格林豪泰(镇江中央大街大润发店)": PriceHit(200, "db", "格林豪泰")},
        meals={
            "breakfast": PriceHit(30, "db", "镇江-breakfast"),
            "lunch": PriceHit(50, "db", "镇江-lunch"),
            "dinner": PriceHit(70, "db", "镇江-dinner"),
        },
        transports={"公共交通": PriceHit(20, "db", "镇江-公共交通")},
    )
    plan = make_plan(days=3)
    report = BudgetCalculator(repo).apply(plan, make_request(days=3))

    assert report.total_by("attraction") == 65 * 3
    assert report.total_by("hotel") == 200 * 2          # 3 天 2 晚
    assert report.total_by("meal") == (30 + 50 + 70) * 3
    assert report.total_by("transport") == 20 * 3
    assert report.total == 1105

    # 明细被回写，保证「明细相加 = 汇总」
    assert plan.days[0].attractions[0].ticket_price == 65
    assert plan.days[0].hotel.estimated_cost == 200
    assert plan.days[0].meals[0].estimated_cost == 30

    assert plan.budget is not None
    assert plan.budget.total == 1105
    assert plan.budget.total_attractions == 195
    assert plan.budget.total_hotels == 400
    assert plan.budget.total_meals == 450
    assert plan.budget.total_transportation == 60


def test_all_miss_falls_back_to_plan_values():
    plan = make_plan(days=3)
    report = BudgetCalculator(FakeRepository()).apply(plan, make_request(days=3))

    assert report.total_by("attraction") == 50 * 3
    assert report.total_by("hotel") == 300 * 2
    assert report.total_by("meal") == (20 + 40 + 60) * 3
    assert report.total_by("transport") == 30 * 3      # 默认公共交通 30/天
    assert report.total == 150 + 600 + 360 + 90

    sources = {item.source for item in report.items}
    assert "plan" in sources
    assert "default" in sources


def test_zero_values_use_defaults():
    plan = make_plan(days=3, ticket_price=0, hotel_cost=0, meal_costs=(0, 0, 0))
    report = BudgetCalculator(FakeRepository()).apply(plan, make_request(days=3))

    assert report.total_by("attraction") == 0
    assert report.total_by("hotel") == 200 * 2
    assert report.total_by("meal") == (30 + 50 + 70) * 3
    assert report.total_by("transport") == 90
    assert report.total == 400 + 450 + 90


def test_one_day_trip_charges_one_night():
    plan = make_plan(days=1)
    report = BudgetCalculator(FakeRepository()).apply(plan, make_request(days=1))

    hotel_items = [item for item in report.items if item.category == "hotel"]
    assert len(hotel_items) == 1
    assert report.total_by("hotel") == 300


def test_transport_mode_mapping():
    repo = FakeRepository(transports={"打车": PriceHit(60, "db", "镇江-打车")})
    plan = make_plan(days=2)
    report = BudgetCalculator(repo).apply(plan, make_request(days=2, transportation="打车"))

    assert report.total_by("transport") == 60 * 2


def test_summary_contains_sources():
    plan = make_plan(days=2)
    report = BudgetCalculator(FakeRepository()).apply(plan, make_request(days=2))
    summary = report.summary()
    assert "预算重算" in summary
    assert "合计" in summary


def test_over_budget_is_computed():
    plan = make_plan(days=3)
    # 全部走兜底：门票 150 + 酒店 600 + 餐饮 360 + 交通 90 = 1200
    report = BudgetCalculator(FakeRepository()).apply(
        plan, make_request(days=3, budget_limit=1000)
    )

    assert report.total == 1200
    assert plan.budget_limit == 1000
    assert plan.over_budget == 200


def test_within_budget_has_no_overage():
    plan = make_plan(days=3)
    report = BudgetCalculator(FakeRepository()).apply(
        plan, make_request(days=3, budget_limit=5000)
    )

    assert report.total == 1200
    assert plan.budget_limit == 5000
    assert plan.over_budget == 0


def test_no_limit_means_zero_overage():
    plan = make_plan(days=3)
    BudgetCalculator(FakeRepository()).apply(plan, make_request(days=3))

    assert plan.budget_limit is None
    assert plan.over_budget == 0

"""Domain contracts for the Zhenjiang trip planner.

These models are the boundary between the deterministic engine and the LLM:
    - facts come from the data layer
    - PlanDraft contains only IDs, never prices/addresses/coordinates
    - Validator and Budget own the hard constraints

Keep these models free of FastAPI / SQLAlchemy / LLM SDK dependencies so they
can be unit-tested and later mapped to Java DTOs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------
class TripRequest(BaseModel):
    """User request, already normalised by the API layer."""

    model_config = ConfigDict(extra="ignore")

    city: str = "镇江"
    start_date: str
    end_date: str
    travel_days: int = Field(ge=1, le=7)
    transportation: str = "公共交通"
    accommodation: str = "经济型酒店"
    preferences: list[str] = Field(default_factory=list)
    free_text_input: str = Field(default="", max_length=500)
    budget_limit: int | None = Field(default=None, ge=0)
    party: Literal["solo", "couple", "family", "elderly"] = "solo"
    pace: Literal["relaxed", "normal", "packed"] = "normal"
    must_see_ids: list[str] = Field(default_factory=list)

    @field_validator("city")
    @classmethod
    def _only_zhenjiang(cls, value: str) -> str:
        value = value.strip()
        if value != "镇江":
            raise ValueError("Day 1 只支持镇江")
        return value

    @field_validator("transportation")
    @classmethod
    def _known_transport(cls, value: str) -> str:
        value = value.strip()
        allowed = {"公共交通", "步行", "打车", "自驾", "混合"}
        if value not in allowed:
            raise ValueError(f"交通方式必须是 {sorted(allowed)} 之一")
        return value

    @field_validator("accommodation")
    @classmethod
    def _non_empty_accommodation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("住宿偏好不能为空")
        return value

    @model_validator(mode="after")
    def _validate_dates(self) -> "TripRequest":
        try:
            start = date.fromisoformat(self.start_date)
            end = date.fromisoformat(self.end_date)
        except ValueError as exc:
            raise ValueError("日期必须是 YYYY-MM-DD") from exc
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        actual_days = (end - start).days + 1
        if actual_days != self.travel_days:
            raise ValueError(
                f"travel_days={self.travel_days} 与日期区间 {actual_days} 天不一致"
            )
        return self


# ---------------------------------------------------------------------------
# Facts: typed candidates with stable IDs
# ---------------------------------------------------------------------------
class AttractionCandidate(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    area: str
    category: str
    tags: list[str] = Field(default_factory=list)
    ticket_price: int = Field(default=0, ge=0)
    price_note: str = ""
    duration_min: int = Field(default=90, gt=0)
    open_hours: str = ""
    closed_days: list[int] = Field(default_factory=list)
    indoor: bool = False
    walking_level: int = Field(default=2, ge=1, le=3)
    must_see: bool = False
    season: list[str] = Field(default_factory=lambda: ["全年"])
    lat: float
    lng: float
    description: str = ""
    address: str = ""
    source_url: str = ""
    last_verified: str = ""
    coord_source: str = "manual"

    @field_validator("closed_days")
    @classmethod
    def _valid_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("closed_days 只能是 0..6（0=周一）")
        return sorted(set(value))

    @field_validator("season")
    @classmethod
    def _default_season(cls, value: list[str]) -> list[str]:
        return value or ["全年"]

    def is_open_on(self, weekday: int) -> bool:
        return weekday not in self.closed_days

    def brief(self) -> dict[str, Any]:
        """Compact payload for the Planner prompt; no long description."""
        return {
            "id": self.id,
            "name": self.name,
            "area": self.area,
            "tags": self.tags,
            "ticket_price": self.ticket_price,
            "duration_min": self.duration_min,
            "must_see": self.must_see,
            "indoor": self.indoor,
            "walking_level": self.walking_level,
            "open_hours": self.open_hours,
        }


class HotelCandidate(BaseModel):
    id: str
    name: str
    tier: str
    area: str
    price_per_night: int = Field(ge=0)
    lat: float
    lng: float
    source_url: str = ""
    last_verified: str = ""
    note: str = ""

    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "area": self.area,
            "price_per_night": self.price_per_night,
        }


class RestaurantCandidate(BaseModel):
    id: str
    name: str
    meal_types: list[str] = Field(default_factory=list)
    area: str
    avg_price: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list)
    lat: float
    lng: float
    source_url: str = ""
    last_verified: str = ""
    note: str = ""

    def serves(self, meal_type: str) -> bool:
        return meal_type in self.meal_types

    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "meal_types": self.meal_types,
            "area": self.area,
            "avg_price": self.avg_price,
            "tags": self.tags,
        }


class TransportFact(BaseModel):
    id: str
    from_station: str
    to_area: str
    mode: str
    duration_min: int = Field(gt=0)
    price: int = Field(ge=0)
    source_url: str = ""
    last_verified: str = ""
    note: str = ""


class WeatherFact(BaseModel):
    date: str
    day_weather: str = ""
    night_weather: str = ""
    day_temp: int = 0
    night_temp: int = 0
    precipitation_prob: int = Field(default=0, ge=0, le=100)
    source: str = "fake"
    is_forecast: bool = False

    def brief(self) -> str:
        return (
            f"{self.date} {self.day_weather} {self.day_temp}℃"
            f" 降水{self.precipitation_prob}%"
        )


class Facts(BaseModel):
    city: str = "镇江"
    data_version: str = ""
    attractions: list[AttractionCandidate] = Field(default_factory=list)
    hotels: list[HotelCandidate] = Field(default_factory=list)
    restaurants: list[RestaurantCandidate] = Field(default_factory=list)
    transports: list[TransportFact] = Field(default_factory=list)
    weather: list[WeatherFact] = Field(default_factory=list)

    def attraction_by_id(self, attraction_id: str) -> AttractionCandidate | None:
        return next((item for item in self.attractions if item.id == attraction_id), None)

    def hotel_by_id(self, hotel_id: str) -> HotelCandidate | None:
        return next((item for item in self.hotels if item.id == hotel_id), None)

    def restaurant_by_id(self, restaurant_id: str) -> RestaurantCandidate | None:
        return next(
            (item for item in self.restaurants if item.id == restaurant_id), None
        )

    def transport_by_id(self, transport_id: str) -> TransportFact | None:
        return next((item for item in self.transports if item.id == transport_id), None)

    @property
    def must_see_attractions(self) -> list[AttractionCandidate]:
        return [item for item in self.attractions if item.must_see]

    def weather_by_date(self, target: str) -> WeatherFact | None:
        return next((item for item in self.weather if item.date == target), None)

    def summary(self) -> dict[str, int]:
        return {
            "attractions": len(self.attractions),
            "hotels": len(self.hotels),
            "restaurants": len(self.restaurants),
            "transports": len(self.transports),
            "weather": len(self.weather),
        }


# ---------------------------------------------------------------------------
# Plan draft: IDs only
# ---------------------------------------------------------------------------
class MealChoice(BaseModel):
    type: Literal["breakfast", "lunch", "dinner"]
    restaurant_id: str


class DayPlanDraft(BaseModel):
    date: str
    attraction_ids: list[str] = Field(min_length=1, max_length=4)
    hotel_id: str = Field(min_length=1)
    meals: list[MealChoice] = Field(min_length=1, max_length=4)
    transport_mode: str = "公共交通"
    theme: str = ""

    @field_validator("attraction_ids")
    @classmethod
    def _no_duplicate_attractions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("同一天不能重复选择同一个景点 ID")
        return value


class PlanDraft(BaseModel):
    days: list[DayPlanDraft] = Field(min_length=1, max_length=7)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_dates(self) -> "PlanDraft":
        dates = [day.date for day in self.days]
        if len(set(dates)) != len(dates):
            raise ValueError("PlanDraft 的日期不能重复")
        return self


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class ValidationIssue(BaseModel):
    code: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    target: str = ""
    message: str
    suggestion: str = ""


class ValidationResult(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    repaired: bool = False

    @property
    def has_blocking(self) -> bool:
        return any(item.severity == "blocking" for item in self.issues)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.has_blocking

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: Literal["blocking", "warning", "info"] = "blocking",
        target: str = "",
        suggestion: str = "",
    ) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                severity=severity,
                target=target,
                message=message,
                suggestion=suggestion,
            )
        )


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
BudgetCategory = Literal["attraction", "hotel", "meal", "transport"]


class BudgetLine(BaseModel):
    category: BudgetCategory
    ref_id: str
    name: str
    amount: int = Field(ge=0)
    source: str = "csv"
    detail: str = ""


class BudgetReport(BaseModel):
    lines: list[BudgetLine] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    budget_limit: int | None = Field(default=None, ge=0)
    over_budget: int = Field(default=0, ge=0)

    @classmethod
    def from_lines(
        cls,
        lines: list[BudgetLine],
        budget_limit: int | None = None,
    ) -> "BudgetReport":
        total = sum(line.amount for line in lines)
        over = (
            max(total - budget_limit, 0)
            if budget_limit is not None and budget_limit > 0
            else 0
        )
        return cls(
            lines=lines,
            total=total,
            budget_limit=budget_limit,
            over_budget=over,
        )

    @model_validator(mode="after")
    def _identity(self) -> "BudgetReport":
        expected_total = sum(line.amount for line in self.lines)
        if self.total != expected_total:
            raise ValueError(
                f"预算恒等式失败: total={self.total}, lines={expected_total}"
            )
        expected_over = (
            max(self.total - self.budget_limit, 0)
            if self.budget_limit is not None and self.budget_limit > 0
            else 0
        )
        if self.over_budget != expected_over:
            raise ValueError(
                f"over_budget 不一致: {self.over_budget} != {expected_over}"
            )
        return self

    def total_by(self, category: BudgetCategory) -> int:
        return sum(line.amount for line in self.lines if line.category == category)

    def summary(self) -> dict[str, int]:
        return {
            "attraction": self.total_by("attraction"),
            "hotel": self.total_by("hotel"),
            "meal": self.total_by("meal"),
            "transport": self.total_by("transport"),
            "total": self.total,
        }


# ---------------------------------------------------------------------------
# Narrative (Day 3 Narrator, defined now so TripContext is stable)
# ---------------------------------------------------------------------------
class TipCard(BaseModel):
    text: str
    source_id: str = ""


class DayNarrative(BaseModel):
    date: str
    description: str
    tips: list[TipCard] = Field(default_factory=list)


class Narrative(BaseModel):
    days: list[DayNarrative] = Field(default_factory=list)
    overall_suggestions: str = ""

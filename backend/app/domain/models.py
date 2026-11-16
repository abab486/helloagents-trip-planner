"""镇江行程助手的领域模型，也就是"确定性引擎"和"LLM"之间那道墙。

三条分工：
    - facts 只从数据层来，模型自己不查库
    - PlanDraft 里只有 ID，永远不出现价格/地址/坐标
    - 硬约束归 Validator 和 Budget 管，模型只负责形状

这里不 import FastAPI / SQLAlchemy / LLM SDK：能单测，将来也能映射成 Java DTO。
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
# 输入：用户请求
# ---------------------------------------------------------------------------
# 进门先过安检：城市 / 交通 / 住宿 / 日期四道关卡
# API 层归一化之后才走到这儿，所以这里只管"能不能进"，不管"好不好"
class TripRequest(BaseModel):
    """用户请求，进 DAG 之前已经被 API 层归一化过。"""

    model_config = ConfigDict(extra="ignore")

    city: str = "镇江"
    start_date: str
    end_date: str
    # 和 PlanDraft 的上限对齐：最多 7 天，最少 1 天
    travel_days: int = Field(ge=1, le=7)
    transportation: str = "公共交通"
    accommodation: str = "经济型酒店"
    preferences: list[str] = Field(default_factory=list)
    free_text_input: str = Field(default="", max_length=500)
    # 0 是合法的：但预算 0 在 BudgetReport 里会被当成"不限预算"，见那边的注释
    budget_limit: int | None = Field(default=None, ge=0)
    party: Literal["solo", "couple", "family", "elderly"] = "solo"
    pace: Literal["relaxed", "normal", "packed"] = "normal"
    # 这里不查 ID 是否存在，传 A999 也能进，要等 validate_plan 才报
    must_see_ids: list[str] = Field(default_factory=list)

    # 只认镇江，别的城市直接拒（Day 1 只有镇江一份数据）
    @field_validator("city")
    @classmethod
    def _only_zhenjiang(cls, value: str) -> str:
        value = value.strip()
        if value != "镇江":
            raise ValueError("Day 1 只支持镇江")
        return value

    # 交通方式是白名单，前端传"高铁"这种也进不来
    @field_validator("transportation")
    @classmethod
    def _known_transport(cls, value: str) -> str:
        value = value.strip()
        allowed = {"公共交通", "步行", "打车", "自驾", "混合"}
        if value not in allowed:
            raise ValueError(f"交通方式必须是 {sorted(allowed)} 之一")
        return value

    # 住宿偏好不能空着，后面算预算要用它选酒店档位
    @field_validator("accommodation")
    @classmethod
    def _non_empty_accommodation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("住宿偏好不能为空")
        return value

    # 日期是冗余表达的裁判：travel_days 和起止日期必须对得上
    # 前端很容易传"3 天但日期跨 4 天"，这里直接掐掉，省得脏数据往下流
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
# 事实层：带稳定 ID 的候选对象
# ---------------------------------------------------------------------------
# 景点：22 个字段，是 Facts 里信息量最大的一张表
# 稳定 ID（A001 这种）是整条链路的锚点，Planner 只认它，不认名字
class AttractionCandidate(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    area: str
    category: str
    tags: list[str] = Field(default_factory=list)
    # 0 有两种含义：真免费，或价格待核实 —— 看 price_note 区分，代码不区分
    ticket_price: int = Field(default=0, ge=0)
    price_note: str = ""
    duration_min: int = Field(default=90, gt=0)
    open_hours: str = ""
    # 0=周一 ... 6=周日；空列表表示"不知道"而不是"不闭馆"
    closed_days: list[int] = Field(default_factory=list)
    # 1=室内为主，下雨天筛景点就靠这个字段
    indoor: bool = False
    # 1 低 / 2 中 / 3 高，带父母和亲子场景用来限强度
    walking_level: int = Field(default=2, ge=1, le=3)
    must_see: bool = False
    season: list[str] = Field(default_factory=lambda: ["全年"])
    lat: float
    lng: float
    # description 是给 Narrator 的素材，故意不进 brief()，省 prompt token
    description: str = ""
    address: str = ""
    source_url: str = ""
    last_verified: str = ""
    # amap / manual / unknown：坐标是人工估的还是高德校准的，下游要能分辨
    coord_source: str = "manual"

    # 周几闭馆必须是 0..6，顺便排序去重
    # loader 里 _to_int(day, -1) 故意塞 -1 进来，就是让脏数据在这儿当场炸掉
    @field_validator("closed_days")
    @classmethod
    def _valid_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("closed_days 只能是 0..6（0=周一）")
        return sorted(set(value))

    # 季节留空就当全年，避免空列表把所有季节都筛掉
    @field_validator("season")
    @classmethod
    def _default_season(cls, value: list[str]) -> list[str]:
        return value or ["全年"]

    # 传 0..6 判断今天开不开门，时区/真实日历不管，只按星期几算
    def is_open_on(self, weekday: int) -> bool:
        return weekday not in self.closed_days

    # 给 LLM 看的裁剪版：22 个字段只留 12 个，实测紧凑 JSON 下体积少 54%
    # 除了省 token，还顺手隔离了职责：description 那种叙事素材归 Narrator，Planner 只做决策
    # 注意体积大头是字段名和 JSON 结构，不是中文内容（汉字只占 296/3764 字符）
    def brief(self) -> dict[str, Any]:
        """给 Planner 的紧凑载荷，不含长描述。"""
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
            "closed_days": self.closed_days,
            "season": self.season,
        }


# 酒店：只按档位（经济型/舒适型/豪华型/民宿）选，没有房型和库存概念
# price_per_night 是挂牌价，不是实时房价
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

    # 给 LLM 看的版本，砍掉坐标和来源信息
    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "area": self.area,
            "price_per_night": self.price_per_night,
        }


# 餐厅：meal_types 决定它能当早餐/午餐/晚餐中的哪几顿
# 一家店可以同时供午晚餐，所以这是个多值字段
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

    # 判断这家店能不能被安排到某一餐，validate_plan 查餐型时用
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


# 交通：站到区的参考耗时和票价，不是实时班次
# 只够回答"从镇江站到京口区大概多久、多少钱"
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


# 天气：现在全是假数据（loader.build_fake_weather 硬编码 4 天模板）
# source / is_forecast 两个字段是用来"自报假"的，但下游渲染时没人展示
class WeatherFact(BaseModel):
    date: str
    day_weather: str = ""
    night_weather: str = ""
    day_temp: int = 0
    night_temp: int = 0
    precipitation_prob: int = Field(default=0, ge=0, le=100)
    source: str = "fake"
    is_forecast: bool = False

    # 一行式摘要，给 trace 和日志用，不进最终行程文案
    def brief(self) -> str:
        return (
            f"{self.date} {self.day_weather} {self.day_temp}℃"
            f" 降水{self.precipitation_prob}%"
        )


# 一次请求的全部事实：4 张表 + 天气，外加数据版本号
# 它由 load_facts 一次装好，之后在 DAG 里只读不改
class Facts(BaseModel):
    city: str = "镇江"
    # 跟 CSV 的 manifest.json 对齐，用来回答"这次结果基于哪版数据"
    data_version: str = ""
    attractions: list[AttractionCandidate] = Field(default_factory=list)
    hotels: list[HotelCandidate] = Field(default_factory=list)
    restaurants: list[RestaurantCandidate] = Field(default_factory=list)
    transports: list[TransportFact] = Field(default_factory=list)
    weather: list[WeatherFact] = Field(default_factory=list)

    # 下面 4 个 by_id 都是线性扫描，不是字典索引
    # 60 行数据下感觉不到，但这也是"没有数据库索引"的代价之一
    # 找不到统一返回 None，不抛异常：判不判空是调用方的事，漏判就 AttributeError
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

    # 标了 must_see 的景点，用户没点名时 Planner 会优先排这些
    @property
    def must_see_attractions(self) -> list[AttractionCandidate]:
        return [item for item in self.attractions if item.must_see]

    # 按日期取天气，日期是 ISO 字符串，直接比字符串不解析成 date
    def weather_by_date(self, target: str) -> WeatherFact | None:
        return next((item for item in self.weather if item.date == target), None)

    # 各表条数，用来做日志和 trace，不作为业务判断依据
    def summary(self) -> dict[str, int]:
        return {
            "attractions": len(self.attractions),
            "hotels": len(self.hotels),
            "restaurants": len(self.restaurants),
            "transports": len(self.transports),
            "weather": len(self.weather),
        }


# ---------------------------------------------------------------------------
# 草稿层：LLM 只能吐 ID，不能吐钱和坐标
# ---------------------------------------------------------------------------
# 一顿饭：餐型 + 餐厅 ID，没有菜名也没有价格
# 价格由 budget_plan 查 Facts 算，模型不许自己编
class MealChoice(BaseModel):
    type: Literal["breakfast", "lunch", "dinner"]
    restaurant_id: str


# 一天：1–4 个景点、1 个酒店、1–4 顿饭
# 这里的 min/max 只是防模型输出离谱数量，不表达业务规则
class DayPlanDraft(BaseModel):
    date: str
    attraction_ids: list[str] = Field(min_length=1, max_length=4)
    hotel_id: str = Field(min_length=1)
    # max_length=4 但没查餐型是否重复：两个 lunch 也能过，这个洞在 planner 层也没补上
    meals: list[MealChoice] = Field(min_length=1, max_length=4)
    transport_mode: str = "公共交通"
    theme: str = ""

    # 同一天不能把同一个景点排两次，这是模型层唯一的景点规则
    # 至于"景点存不存在、开不开门、走不走得动"，全归 validate_plan 管
    @field_validator("attraction_ids")
    @classmethod
    def _no_duplicate_attractions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("同一天不能重复选择同一个景点 ID")
        return value


# 整份草稿：1–7 天 + 若干条备注
# 模型层只查"日期不重复"，其余 14 条语义规则都在 walking_skeleton.validate_plan
class PlanDraft(BaseModel):
    days: list[DayPlanDraft] = Field(min_length=1, max_length=7)
    notes: list[str] = Field(default_factory=list)

    # 日期不能重复，否则同一份行程里会出现两个"11-16"
    @model_validator(mode="after")
    def _unique_dates(self) -> "PlanDraft":
        dates = [day.date for day in self.days]
        if len(set(dates)) != len(dates):
            raise ValueError("PlanDraft 的日期不能重复")
        return self


# ---------------------------------------------------------------------------
# 裁判：校验结果
# ---------------------------------------------------------------------------
# 一条问题：code 给机器筛，message 给人看，suggestion 是改法
# severity 三档只说一件事：blocking 会挡住行程，warning 只提示
class ValidationIssue(BaseModel):
    code: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    target: str = ""
    message: str
    suggestion: str = ""


# 一份体检报告：一堆问题 + "有没有被自动修过"
class ValidationResult(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    repaired: bool = False

    # 有没有致命问题，内部判断用，不进序列化
    @property
    def has_blocking(self) -> bool:
        return any(item.severity == "blocking" for item in self.issues)

    # 结论给外部看，所以进 model_dump()；前端只需要知道"过没过"
    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.has_blocking

    # 一条一条往报告里记，省得每次都手写 ValidationIssue(...)
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
# 账本：预算
# ---------------------------------------------------------------------------
# 只有四类花费，别的一律不算（购物、特产、门票优惠都不在此列）
BudgetCategory = Literal["attraction", "hotel", "meal", "transport"]


# 一行账：哪一类、哪个 ID、叫什么、多少钱
# source 现在恒为 csv，留着是为了将来标"这条是数据库价还是估算价"
class BudgetLine(BaseModel):
    category: BudgetCategory
    ref_id: str
    name: str
    amount: int = Field(ge=0)
    source: str = "csv"
    detail: str = ""


# 预算报告：明细 + 总额 + 限额 + 超了多少
# total 是冗余字段（能 sum 出来），但既然存了就必须保证平账
class BudgetReport(BaseModel):
    lines: list[BudgetLine] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    budget_limit: int | None = Field(default=None, ge=0)
    over_budget: int = Field(default=0, ge=0)

    # 推荐从这儿造：先算总额再传进去，别手写 total
    @classmethod
    def from_lines(
        cls,
        lines: list[BudgetLine],
        budget_limit: int | None = None,
    ) -> "BudgetReport":
        total = sum(line.amount for line in lines)
        # 注意 budget_limit=0 会走到 else：0 元预算被当成"不限预算"
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

    # 恒等式：total 必须等于明细之和，超支额也必须自洽，否则对象根本造不出来
    # 这比事后写测试断言硬：测试可能忘，构造函数不会忘
    # 代价是同一条公式在上面 from_lines 里又写了一遍，改的时候要改两处
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

    # 按类别小计，每次都遍历一遍明细；summary() 会连调四次，共四趟
    def total_by(self, category: BudgetCategory) -> int:
        return sum(line.amount for line in self.lines if line.category == category)

    # 四类各多少钱 + 总额，前端画预算饼图直接用这个
    def summary(self) -> dict[str, int]:
        return {
            "attraction": self.total_by("attraction"),
            "hotel": self.total_by("hotel"),
            "meal": self.total_by("meal"),
            "transport": self.total_by("transport"),
            "total": self.total,
        }


# ---------------------------------------------------------------------------
# 叙述：Day 3 的 Narrator 才用，现在先定形状
# ---------------------------------------------------------------------------
# 一条小贴士：文案 + 它来自哪张知识卡
# source_id 留着是为了将来能追溯"这句话不是编的"
class TipCard(BaseModel):
    text: str
    source_id: str = ""


# 一天的叙述：日期 + 一段描述 + 若干贴士
class DayNarrative(BaseModel):
    date: str
    description: str
    tips: list[TipCard] = Field(default_factory=list)


# 整份叙述。现在没人构造它，纯粹是提前占位
# 提前定的理由是 TripContext 要稳定：晚点加字段，五个节点的类型签名全得改
class Narrative(BaseModel):
    days: list[DayNarrative] = Field(default_factory=list)
    overall_suggestions: str = ""

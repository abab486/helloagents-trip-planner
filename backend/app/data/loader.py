"""CSV 到领域事实（Facts）的装载器。

Day 1 故意不依赖 MySQL：walking skeleton 直接读这几张 CSV，它们之后会原样
导进 `zj_*` 表。好处是"数据长什么样"这份契约在上基础设施之前就能被测试。
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..domain.models import (
    AttractionCandidate,
    Facts,
    HotelCandidate,
    RestaurantCandidate,
    TransportFact,
    WeatherFact,
)
from .validate_zhenjiang import validate_dataset
from .zhenjiang import DATA_DIR

_FAKE_WEATHER = (
    # day_weather, night_weather, day_temp, night_temp, precipitation_prob
    ("晴", "多云", 19, 10, 10),
    ("多云", "阴", 17, 9, 20),
    ("小雨", "阴", 14, 8, 70),
    ("晴", "晴", 20, 11, 0),
)


def _read_rows(filename: str, data_dir: Path = DATA_DIR) -> list[dict[str, str]]:
    """整表读进内存，表头当 key。newline="" 是为了不让 Windows 的 \r\n 多造出空行。"""
    path = data_dir / filename
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split(value: str) -> list[str]:
    """把 `a|b|c` 拆成列表，顺手丢掉空串，所以结尾多个竖线也不会产生空元素。"""
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def _to_int(value: str, default: int = 0) -> int:
    """转不动就吃默认值、不抛错。CSV 没有类型，兜底的责任在这一层。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: str, default: float = 0.0) -> float:
    """同上，坐标用；写错就掉到 0.0，等于没有坐标。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: str) -> bool:
    """只认这四种写法，大写 "TRUE"/"YES" 会被判成 False。"""
    return (value or "").strip() in {"1", "true", "True", "yes"}


def load_manifest(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """读 manifest.json：数据版本号、条数、质量说明都在这里，没有校验。"""
    return json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))


def _load_attractions(data_dir: Path) -> list[AttractionCandidate]:
    """景点表。id/name/area/category 用下标取（缺了就炸），其余字段用 get 给默认值。"""
    result: list[AttractionCandidate] = []
    for row in _read_rows("attractions.csv", data_dir):
        result.append(
            AttractionCandidate(
                id=row["id"].strip(),
                name=row["name"].strip(),
                aliases=_split(row.get("aliases", "")),
                area=row["area"].strip(),
                category=row["category"].strip(),
                tags=_split(row.get("tags", "")),
                ticket_price=_to_int(row.get("ticket_price", "0")),
                price_note=row.get("price_note", "").strip(),
                duration_min=_to_int(row.get("duration_min", "90"), 90),
                open_hours=row.get("open_hours", "").strip(),
                closed_days=[
                    # -1 是故意的"毒值"：models 只允许 0..6，CSV 里写成"周一"会在这里被 Pydantic 拦下
                    _to_int(day, -1) for day in _split(row.get("closed_days", ""))
                ],
                indoor=_to_bool(row.get("indoor", "0")),
                walking_level=_to_int(row.get("walking_level", "2"), 2),
                must_see=_to_bool(row.get("must_see", "0")),
                season=_split(row.get("season", "")) or ["全年"],
                lat=_to_float(row.get("lat", "0")),
                lng=_to_float(row.get("lng", "0")),
                description=row.get("description", "").strip(),
                address=row.get("address", "").strip(),
                source_url=row.get("source_url", "").strip(),
                last_verified=row.get("last_verified", "").strip(),
                coord_source=row.get("coord_source", "manual").strip(),
            )
        )
    return result

# 读行 → 逐字段转换 → 造 Pydantic 对象
def _load_hotels(data_dir: Path) -> list[HotelCandidate]:
    result: list[HotelCandidate] = []
    for row in _read_rows("hotels.csv", data_dir):
        result.append(
            HotelCandidate(
                id=row["id"].strip(),
                name=row["name"].strip(),
                tier=row["tier"].strip(),
                area=row["area"].strip(),
                price_per_night=_to_int(row.get("price_per_night", "0")),
                lat=_to_float(row.get("lat", "0")),
                lng=_to_float(row.get("lng", "0")),
                source_url=row.get("source_url", "").strip(),
                last_verified=row.get("last_verified", "").strip(),
                note=row.get("note", "").strip(),
            )
        )
    return result


def _load_restaurants(data_dir: Path) -> list[RestaurantCandidate]:
    result: list[RestaurantCandidate] = []
    for row in _read_rows("restaurants.csv", data_dir):
        result.append(
            RestaurantCandidate(
                id=row["id"].strip(),
                name=row["name"].strip(),
                meal_types=_split(row.get("meal_types", "")),
                area=row["area"].strip(),
                avg_price=_to_int(row.get("avg_price", "0")),
                tags=_split(row.get("tags", "")),
                lat=_to_float(row.get("lat", "0")),
                lng=_to_float(row.get("lng", "0")),
                source_url=row.get("source_url", "").strip(),
                last_verified=row.get("last_verified", "").strip(),
                note=row.get("note", "").strip(),
            )
        )
    return result


def _load_transports(data_dir: Path) -> list[TransportFact]:
    result: list[TransportFact] = []
    for row in _read_rows("transports.csv", data_dir):
        result.append(
            TransportFact(
                id=row["id"].strip(),
                from_station=row["from_station"].strip(),
                to_area=row["to_area"].strip(),
                mode=row["mode"].strip(),
                duration_min=_to_int(row.get("duration_min", "0")),
                price=_to_int(row.get("price", "0")),
                source_url=row.get("source_url", "").strip(),
                last_verified=row.get("last_verified", "").strip(),
                note=row.get("note", "").strip(),
            )
        )
    return result


def build_fake_weather(start_date: str, days: int) -> list[WeatherFact]:
    """给 Day 1 walking skeleton 用的确定性假天气。

    按 4 天模板轮转，同一天永远拿到同一份结果（评测可复现）；
    天气是真的假，日期是真的真——Day 2 才换成预报或季节均价。
    """
    if days < 1:
        raise ValueError("days 必须 >= 1")
    start = date.fromisoformat(start_date)
    weather: list[WeatherFact] = []
    for index in range(days):
        current = start + timedelta(days=index)
        day_weather, night_weather, day_temp, night_temp, rain = _FAKE_WEATHER[
            index % len(_FAKE_WEATHER)
        ]
        weather.append(
            WeatherFact(
                date=current.isoformat(),
                day_weather=day_weather,
                night_weather=night_weather,
                day_temp=day_temp,
                night_temp=night_temp,
                precipitation_prob=rain,
                source="fake-climate",
                is_forecast=False,
            )
        )
    return weather


def load_facts(
    start_date: str,
    days: int,
    data_dir: Path = DATA_DIR,
    *,
    validate: bool = True,
) -> Facts:
    """把 CSV 装成 Facts。数据集结构不合法时抛 ValueError。

    validate 默认开着，意味着每次调用都会把 5 张表全量校验一遍（365 行那套规则）。
    数据只有几十行时无所谓，但它是按请求数重复的活儿，没有缓存。
    """
    if validate:
        errors = validate_dataset(data_dir)
        if errors:
            raise ValueError("数据集校验失败:\n" + "\n".join(errors))

    manifest = load_manifest(data_dir)
    return Facts(
        city=manifest.get("city", "镇江"),
        data_version=manifest.get("data_version", ""),
        attractions=_load_attractions(data_dir),
        hotels=_load_hotels(data_dir),
        restaurants=_load_restaurants(data_dir),
        transports=_load_transports(data_dir),
        weather=build_fake_weather(start_date, days),
    )

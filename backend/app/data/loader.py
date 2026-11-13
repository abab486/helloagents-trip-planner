"""CSV -> domain facts loader.

Day 1 deliberately has no MySQL dependency: the walking skeleton reads the
same CSV files that will later be imported into `zj_*` tables. This keeps the
contract testable before infrastructure is wired in.
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
    path = data_dir / filename
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: str) -> bool:
    return (value or "").strip() in {"1", "true", "True", "yes"}


def load_manifest(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    return json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))


def _load_attractions(data_dir: Path) -> list[AttractionCandidate]:
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
    """Deterministic placeholder weather for the Day 1 walking skeleton.

    Day 2 replaces this with real weather facts (forecast or seasonal average).
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
    """Load CSV facts. Raises ValueError if the dataset is structurally invalid."""
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

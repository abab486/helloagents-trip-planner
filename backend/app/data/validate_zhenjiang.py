"""Day 1 镇江数据校验。

目标：在接 MySQL / LLM 之前，先把 CSV 的数据质量问题挡住：
    - 数量是否符合冻结范围
    - ID / 名称是否唯一
    - 必填字段、来源、核实日期是否齐全
    - 经纬度、闭馆日、枚举值是否合法
    - 知识卡是否引用真实景点

用法（在 backend 目录下）：
    python -m app.data.validate_zhenjiang
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .zhenjiang import DATA_DIR

EXPECTED_COUNTS = {
    "attractions": 18,
    "hotels": 10,
    "restaurants": 12,
    "transports": 8,
    "knowledge_cards": 12,
}

FILES = {
    "attractions": "attractions.csv",
    "hotels": "hotels.csv",
    "restaurants": "restaurants.csv",
    "transports": "transports.csv",
    "knowledge_cards": "knowledge_cards.csv",
}

AREAS = {
    "京口区",
    "润州区",
    "丹徒区",
    "句容市",
    "丹阳市",
    "扬中市",
    "镇江新区",
}

CATEGORIES = {
    "寺庙",
    "古街",
    "古建",
    "博物馆",
    "山岳",
    "园林",
    "工业旅游",
    "名人故居",
    "公园",
    "红色景点",
}

TIERS = {"经济型", "舒适型", "豪华型", "民宿"}
MEAL_TYPES = {"breakfast", "lunch", "dinner"}
TRANSPORT_MODES = {"公共交通", "步行", "打车", "自驾"}
SEASONS = {"春", "夏", "秋", "冬", "全年"}
COORD_SOURCES = {"amap", "manual", "unknown"}

REQUIRED = {
    "attractions": (
        "id",
        "name",
        "area",
        "category",
        "tags",
        "ticket_price",
        "duration_min",
        "indoor",
        "walking_level",
        "must_see",
        "lat",
        "lng",
        "description",
        "source_url",
        "last_verified",
    ),
    "hotels": (
        "id",
        "name",
        "tier",
        "area",
        "price_per_night",
        "lat",
        "lng",
        "source_url",
        "last_verified",
    ),
    "restaurants": (
        "id",
        "name",
        "meal_types",
        "area",
        "avg_price",
        "lat",
        "lng",
        "source_url",
        "last_verified",
    ),
    "transports": (
        "id",
        "from_station",
        "to_area",
        "mode",
        "duration_min",
        "price",
        "source_url",
        "last_verified",
    ),
    "knowledge_cards": (
        "id",
        "attraction_id",
        "topic",
        "content",
        "source_url",
        "last_verified",
    ),
}


def read_csv(filename: str, data_dir: Path = DATA_DIR) -> list[dict[str, str]]:
    path = data_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_pipe(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def _is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _check_required(
    rows: list[dict[str, str]], kind: str, errors: list[str]
) -> None:
    for index, row in enumerate(rows, start=2):
        for field in REQUIRED[kind]:
            if not (row.get(field) or "").strip():
                errors.append(f"{FILES[kind]}:{index} 缺少必填字段 {field}")


def _check_common(
    rows: list[dict[str, str]], kind: str, errors: list[str]
) -> None:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, row in enumerate(rows, start=2):
        prefix = f"{FILES[kind]}:{index}"
        row_id = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()

        if row_id in seen_ids:
            errors.append(f"{prefix} ID 重复: {row_id}")
        seen_ids.add(row_id)

        if name and name in seen_names:
            errors.append(f"{prefix} 名称重复: {name}")
        seen_names.add(name)

        if not _is_http_url((row.get("source_url") or "").strip()):
            errors.append(f"{prefix} source_url 不是 http(s) URL")

        if not _is_date((row.get("last_verified") or "").strip()):
            errors.append(f"{prefix} last_verified 不是 YYYY-MM-DD")


def validate_dataset(data_dir: Path = DATA_DIR) -> list[str]:
    """返回错误列表；空列表表示数据通过校验。"""
    errors: list[str] = []
    data: dict[str, list[dict[str, str]]] = {}

    for kind, filename in FILES.items():
        try:
            rows = read_csv(filename, data_dir)
        except FileNotFoundError as exc:
            errors.append(str(exc))
            continue
        data[kind] = rows

        expected = EXPECTED_COUNTS[kind]
        if len(rows) != expected:
            errors.append(
                f"{filename} 行数 {len(rows)} != 冻结值 {expected}"
            )

        _check_required(rows, kind, errors)
        _check_common(rows, kind, errors)

    # ---- 景点 ----
    attractions = data.get("attractions", [])
    must_see_count = 0
    for index, row in enumerate(attractions, start=2):
        prefix = f"attractions.csv:{index}"
        if row.get("area") not in AREAS:
            errors.append(f"{prefix} area 不在允许集合: {row.get('area')}")
        if row.get("category") not in CATEGORIES:
            errors.append(f"{prefix} category 不在允许集合: {row.get('category')}")
        if not _is_int(row.get("ticket_price", "")):
            errors.append(f"{prefix} ticket_price 不是整数")
        elif int(row["ticket_price"]) < 0:
            errors.append(f"{prefix} ticket_price 不能为负")
        if not _is_int(row.get("duration_min", "")):
            errors.append(f"{prefix} duration_min 不是整数")
        elif int(row["duration_min"]) <= 0:
            errors.append(f"{prefix} duration_min 必须大于 0")
        if row.get("indoor") not in {"0", "1"}:
            errors.append(f"{prefix} indoor 必须是 0/1")
        if row.get("must_see") not in {"0", "1"}:
            errors.append(f"{prefix} must_see 必须是 0/1")
        if row.get("must_see") == "1":
            must_see_count += 1
        if row.get("walking_level") not in {"1", "2", "3"}:
            errors.append(f"{prefix} walking_level 必须是 1/2/3")
        if row.get("coord_source") not in COORD_SOURCES:
            errors.append(f"{prefix} coord_source 不在允许集合")
        if not _is_float(row.get("lat", "")) or not _is_float(row.get("lng", "")):
            errors.append(f"{prefix} lat/lng 不是数字")
        else:
            lat, lng = float(row["lat"]), float(row["lng"])
            if not (31.5 <= lat <= 32.5):
                errors.append(f"{prefix} lat 超出镇江范围: {lat}")
            if not (118.8 <= lng <= 120.0):
                errors.append(f"{prefix} lng 超出镇江范围: {lng}")
        for day in _split_pipe(row.get("closed_days", "")):
            if day not in {"0", "1", "2", "3", "4", "5", "6"}:
                errors.append(f"{prefix} closed_days 非法: {day}")
        for season in _split_pipe(row.get("season", "")):
            if season not in SEASONS:
                errors.append(f"{prefix} season 非法: {season}")
        if not _split_pipe(row.get("tags", "")):
            errors.append(f"{prefix} tags 不能为空")
        if not (row.get("price_note") or "").strip():
            errors.append(f"{prefix} price_note 不能为空")

    if must_see_count < 8:
        errors.append(f"must_see 数量 {must_see_count} < 8")

    # ---- 酒店 ----
    for index, row in enumerate(data.get("hotels", []), start=2):
        prefix = f"hotels.csv:{index}"
        if row.get("tier") not in TIERS:
            errors.append(f"{prefix} tier 不在允许集合: {row.get('tier')}")
        if row.get("area") not in AREAS:
            errors.append(f"{prefix} area 不在允许集合: {row.get('area')}")
        if not _is_int(row.get("price_per_night", "")):
            errors.append(f"{prefix} price_per_night 不是整数")
        elif int(row["price_per_night"]) <= 0:
            errors.append(f"{prefix} price_per_night 必须大于 0")

    # ---- 餐厅 ----
    for index, row in enumerate(data.get("restaurants", []), start=2):
        prefix = f"restaurants.csv:{index}"
        meal_types = set(_split_pipe(row.get("meal_types", "")))
        if not meal_types:
            errors.append(f"{prefix} meal_types 不能为空")
        if not meal_types <= MEAL_TYPES:
            errors.append(f"{prefix} meal_types 含非法值: {meal_types - MEAL_TYPES}")
        if row.get("area") not in AREAS:
            errors.append(f"{prefix} area 不在允许集合: {row.get('area')}")
        if not _is_int(row.get("avg_price", "")):
            errors.append(f"{prefix} avg_price 不是整数")
        elif int(row["avg_price"]) <= 0:
            errors.append(f"{prefix} avg_price 必须大于 0")

    # ---- 交通 ----
    for index, row in enumerate(data.get("transports", []), start=2):
        prefix = f"transports.csv:{index}"
        if row.get("mode") not in TRANSPORT_MODES:
            errors.append(f"{prefix} mode 不在允许集合: {row.get('mode')}")
        for field in ("duration_min", "price"):
            if not _is_int(row.get(field, "")):
                errors.append(f"{prefix} {field} 不是整数")
        if _is_int(row.get("duration_min", "")) and int(row["duration_min"]) <= 0:
            errors.append(f"{prefix} duration_min 必须大于 0")
        if _is_int(row.get("price", "")) and int(row["price"]) < 0:
            errors.append(f"{prefix} price 不能为负")

    # ---- 知识卡 ----
    attraction_ids = {row.get("id") for row in attractions}
    for index, row in enumerate(data.get("knowledge_cards", []), start=2):
        prefix = f"knowledge_cards.csv:{index}"
        if row.get("attraction_id") not in attraction_ids:
            errors.append(
                f"{prefix} attraction_id 不存在: {row.get('attraction_id')}"
            )
        if len((row.get("content") or "").strip()) < 20:
            errors.append(f"{prefix} content 太短，至少 20 字")

    # ---- manifest ----
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        errors.append("manifest.json 不存在")
    else:
        try:
            manifest: dict[str, Any] = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            errors.append(f"manifest.json 不是合法 JSON: {exc}")
        else:
            expected = manifest.get("counts", {})
            for kind, count in EXPECTED_COUNTS.items():
                if expected.get(kind) != count:
                    errors.append(
                        f"manifest.counts.{kind}={expected.get(kind)} != {count}"
                    )

    return errors


def main() -> int:
    errors = validate_dataset()
    if errors:
        print(f"[FAIL] 镇江数据集校验失败，共 {len(errors)} 个问题：")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("[OK] 镇江数据集校验通过")
    for kind, filename in FILES.items():
        print(f"  - {filename}: {EXPECTED_COUNTS[kind]} 条")
    print(f"  - must_see: 已满足 >= 8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

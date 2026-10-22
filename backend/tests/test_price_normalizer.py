"""名称归一化单元测试"""

from app.services.price_normalizer import (
    normalize_attraction_name,
    normalize_city,
    normalize_transport_mode,
)


def test_normalize_city_removes_suffix():
    assert normalize_city("镇江市") == "镇江"
    assert normalize_city(" 镇江 ") == "镇江"
    assert normalize_city("") == ""


def test_removes_parentheses():
    assert normalize_attraction_name("金山寺(金山公园内)", "镇江") == "金山寺"
    assert normalize_attraction_name("金山寺（金山公园内）", "镇江") == "金山寺"


def test_removes_sub_spot():
    assert normalize_attraction_name("西津渡历史文化街区-五十三坡", "镇江") == "西津渡历史文化街区"
    assert normalize_attraction_name("西津渡历史文化街区——凉亭", "镇江") == "西津渡历史文化街区"


def test_removes_generic_suffix():
    assert normalize_attraction_name("北固山风景区", "镇江") == "北固山"
    assert normalize_attraction_name("金山湖景区", "镇江") == "金山湖"


def test_removes_city_prefix():
    assert normalize_attraction_name("镇江市金山寺", "镇江") == "金山寺"


def test_keeps_name_starting_with_city():
    # 「镇江博物馆」是景点本名，不能被当成城市前缀剥掉
    assert normalize_attraction_name("镇江博物馆", "镇江") == "镇江博物馆"


def test_keeps_park_name_for_alias_lookup():
    # 「金山公园」是别名，不能被当成通用后缀删掉
    assert normalize_attraction_name("金山公园", "镇江") == "金山公园"


def test_empty_name():
    assert normalize_attraction_name("", "镇江") == ""
    assert normalize_attraction_name(None, "镇江") == ""


def test_transport_mode_mapping():
    assert normalize_transport_mode("公共交通") == "公共交通"
    assert normalize_transport_mode("公交+地铁") == "公共交通"
    assert normalize_transport_mode("打车") == "打车"
    assert normalize_transport_mode("自驾") == "自驾"
    assert normalize_transport_mode("") == "其他"

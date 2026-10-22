"""价格仓储集成测试（需要本地 MySQL，未初始化时自动跳过）"""

import pytest

from app.db.pool import get_connection
from app.db.repository import PriceRepository


@pytest.fixture(scope="module")
def repo():
    connection = get_connection()
    if connection is None:
        pytest.skip("MySQL 不可用，跳过集成测试")
    connection.close()
    return PriceRepository()


def test_attraction_exact(repo):
    hit = repo.get_attraction("镇江", "金山寺")
    assert hit is not None
    assert hit.value == 65
    assert hit.source == "db"


def test_attraction_alias(repo):
    hit = repo.get_attraction("镇江", "金山公园")
    assert hit is not None
    assert hit.value == 65
    assert hit.source == "alias"
    assert hit.matched == "金山寺"


def test_attraction_free(repo):
    hit = repo.get_attraction("镇江", "西津渡")
    assert hit is not None
    assert hit.value == 0


def test_attraction_missing(repo):
    assert repo.get_attraction("镇江", "不存在的景点") is None


def test_hotel_by_name(repo):
    hit = repo.get_hotel("镇江", "格林豪泰(镇江中央大街大润发店)", "经济型")
    assert hit is not None
    assert hit.value == 200


def test_meal_city_and_default(repo):
    assert repo.get_meal("镇江", "lunch").value == 50
    # 未配置的城市走全国默认
    assert repo.get_meal("火星", "lunch").value == 45


def test_transport_city_and_default(repo):
    assert repo.get_transport("镇江", "公共交通").value == 20
    assert repo.get_transport("火星", "公共交通").value == 30

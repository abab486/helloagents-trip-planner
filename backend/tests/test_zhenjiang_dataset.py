"""镇江数据集契约测试：Day 1 先保证数据质量，再谈 DAG/LLM。"""

from app.data.validate_zhenjiang import EXPECTED_COUNTS, validate_dataset
from app.data.zhenjiang import DATA_DIR


def test_zhenjiang_dataset_has_no_errors():
    assert validate_dataset() == []


def test_dataset_files_exist():
    for filename in (
        "attractions.csv",
        "hotels.csv",
        "restaurants.csv",
        "transports.csv",
        "knowledge_cards.csv",
        "manifest.json",
    ):
        assert (DATA_DIR / filename).exists(), filename


def test_expected_counts_are_frozen():
    assert EXPECTED_COUNTS == {
        "attractions": 18,
        "hotels": 10,
        "restaurants": 12,
        "transports": 8,
        "knowledge_cards": 12,
    }

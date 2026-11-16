"""镇江数据集契约测试：Day 1 先保证数据质量，再谈 DAG/LLM。"""

from app.data.validate_zhenjiang import EXPECTED_COUNTS, validate_dataset
from app.data.zhenjiang import DATA_DIR


# 全量跑一遍校验规则，有任何 error 就挂
# 这是"数据不干净就别往下走"的总闸，loader.load_facts 默认也会调它
def test_zhenjiang_dataset_has_no_errors():
    assert validate_dataset() == []


# 六个文件一个都不能少
# 注意 knowledge_cards.csv 在这儿被要求存在，但 loader 根本不读它
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


# 条数被冻结了：加一个景点就得同时改这里和 manifest.json
# 故意写死，防止有人悄悄往 CSV 里塞数据把评测基线带偏
def test_expected_counts_are_frozen():
    assert EXPECTED_COUNTS == {
        "attractions": 18,
        "hotels": 10,
        "restaurants": 12,
        "transports": 8,
        "knowledge_cards": 12,
    }

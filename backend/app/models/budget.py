"""预算计算相关的数据模型"""

from dataclasses import dataclass, field
from typing import Dict, List


# 旧链路专用：新 v1 没有"命中来源"这一层，价格直接读 CSV 的 ticket_price / price_per_night
@dataclass
class PriceHit:
    """一次价格查询的命中结果"""

    value: int
    source: str          # alias / db / fuzzy
    matched: str         # 实际命中的标准名


# 旧链路专用：新 v1 的明细项是 domain/models.py 的 BudgetLine（多一个 detail 字段）
@dataclass
class BudgetItem:
    """单个计费项"""

    category: str        # attraction / hotel / meal / transport
    name: str
    amount: int
    source: str          # alias / db / fuzzy / plan / default


# 旧链路专用：新 v1 的账本是 domain/models.py 的 BudgetReport（构造期强制恒等式），同名但不同物
@dataclass
class BudgetReport:
    """预算重算报告：既用于日志，也方便测试断言"""

    items: List[BudgetItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(item.amount for item in self.items)

    def total_by(self, category: str) -> int:
        return sum(item.amount for item in self.items if item.category == category)

    def stats(self) -> Dict[str, Dict[str, int]]:
        """按「类别 → 来源 → 次数」汇总，用于观察数据命中率"""
        result: Dict[str, Dict[str, int]] = {}
        for item in self.items:
            result.setdefault(item.category, {})
            result[item.category][item.source] = result[item.category].get(item.source, 0) + 1
        return result

    def summary(self) -> str:
        labels = {
            "attraction": "门票",
            "hotel": "酒店",
            "meal": "餐饮",
            "transport": "交通",
        }
        parts = []
        for category in ("attraction", "hotel", "meal", "transport"):
            by_source = self.stats().get(category, {})
            source_text = "/".join(f"{k} {v}" for k, v in sorted(by_source.items()))
            parts.append(f"{labels[category]} {self.total_by(category)}({source_text})")
        return f"预算重算: {' '.join(parts)} | 合计 {self.total}"

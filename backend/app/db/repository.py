"""价格数据访问层

所有 SQL 都集中在这里，上层（BudgetCalculator）只依赖方法签名，
将来换 SQLite/Redis 只需新增一个实现类。
"""

from typing import Optional

from ..db.pool import get_connection
from ..models.budget import PriceHit


class PriceRepository:
    """MySQL 价格查询"""

    def __init__(self) -> None:
        self._warned = False

    # ------------------------------------------------------------------
    # 基础查询
    # ------------------------------------------------------------------
    def _query_one(self, sql: str, params: tuple) -> Optional[dict]:
        conn = get_connection()
        if conn is None:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
        except Exception as exc:  # noqa: BLE001 - 查询失败不应中断请求
            if not self._warned:
                print(f"⚠️ 价格查询失败，后续回退到模型估算值: {exc}")
                self._warned = True
            return None
        finally:
            conn.close()  # PooledDB 的 close 是归还连接

    # ------------------------------------------------------------------
    # 门票
    # ------------------------------------------------------------------
    def get_attraction(self, city: str, name: str) -> Optional[PriceHit]:
        if not name:
            return None

        row = self._query_one(
            "SELECT p.price AS price, p.name AS name "
            "FROM attraction_alias a "
            "JOIN attraction_price p ON p.city = a.city AND p.name = a.name "
            "WHERE a.city = %s AND a.alias = %s LIMIT 1",
            (city, name),
        )
        if row:
            return PriceHit(int(row["price"]), "alias", row["name"])

        row = self._query_one(
            "SELECT price, name FROM attraction_price "
            "WHERE city = %s AND name = %s LIMIT 1",
            (city, name),
        )
        if row:
            return PriceHit(int(row["price"]), "db", row["name"])

        # 兜底：库里的标准名被输入包含（如「镇江金山寺风景区」包含「金山寺」），取最长匹配
        row = self._query_one(
            "SELECT price, name FROM attraction_price "
            "WHERE city = %s AND %s LIKE CONCAT('%%', name, '%%') "
            "ORDER BY LENGTH(name) DESC LIMIT 1",
            (city, name),
        )
        if row:
            return PriceHit(int(row["price"]), "fuzzy", row["name"])

        return None

    # ------------------------------------------------------------------
    # 酒店
    # ------------------------------------------------------------------
    def get_hotel(self, city: str, name: str, tier: str = "") -> Optional[PriceHit]:
        if name:
            row = self._query_one(
                "SELECT price_per_night AS price, name FROM hotel_price "
                "WHERE city = %s AND name = %s LIMIT 1",
                (city, name),
            )
            if row:
                return PriceHit(int(row["price"]), "db", row["name"])

        if tier:
            row = self._query_one(
                "SELECT ROUND(AVG(price_per_night)) AS price FROM hotel_price "
                "WHERE city = %s AND tier = %s",
                (city, tier),
            )
            if row and row["price"] is not None:
                return PriceHit(int(row["price"]), "tier", f"{city}-{tier}均价")

        return None

    # ------------------------------------------------------------------
    # 餐饮（城市 → 全国默认）
    # ------------------------------------------------------------------
    def get_meal(self, city: str, meal_type: str) -> Optional[PriceHit]:
        if not meal_type:
            return None

        row = self._query_one(
            "SELECT price FROM meal_price WHERE city = %s AND meal_type = %s LIMIT 1",
            (city, meal_type),
        )
        if row:
            return PriceHit(int(row["price"]), "db", f"{city}-{meal_type}")

        row = self._query_one(
            "SELECT price FROM meal_price WHERE city = '*' AND meal_type = %s LIMIT 1",
            (meal_type,),
        )
        if row:
            return PriceHit(int(row["price"]), "default", f"*-{meal_type}")
        return None

    # ------------------------------------------------------------------
    # 交通（城市 → 全国默认）
    # ------------------------------------------------------------------
    def get_transport(self, city: str, mode: str) -> Optional[PriceHit]:
        if not mode:
            return None

        row = self._query_one(
            "SELECT price_per_day AS price FROM transport_price "
            "WHERE city = %s AND mode = %s LIMIT 1",
            (city, mode),
        )
        if row:
            return PriceHit(int(row["price"]), "db", f"{city}-{mode}")

        row = self._query_one(
            "SELECT price_per_day AS price FROM transport_price "
            "WHERE city = '*' AND mode = %s LIMIT 1",
            (mode,),
        )
        if row:
            return PriceHit(int(row["price"]), "default", f"*-{mode}")
        return None

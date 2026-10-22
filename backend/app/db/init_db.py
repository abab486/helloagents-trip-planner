"""初始化数据库：建库、建表、补唯一索引、写入种子数据

用法（在 backend 目录下）：
    python -m app.db.init_db

特性：可重复执行（幂等）。如果检测到旧版本的表缺少唯一索引，
会先按「保留最小 id」去重，再补索引，避免种子数据重复写入。
"""

from pathlib import Path

from ..config import get_settings

# 表名 -> (唯一索引名, 唯一列)
UNIQUE_KEYS = {
    "attraction_price": ("uk_city_name", "city, name"),
    "attraction_alias": ("uk_city_alias", "city, alias"),
    "hotel_price": ("uk_city_name", "city, name"),
    "meal_price": ("uk_city_type", "city, meal_type"),
    "transport_price": ("uk_city_mode", "city, mode"),
}


def _split_statements(sql: str) -> list[str]:
    """按分号拆分 SQL，忽略注释行和空语句"""
    kept = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        kept.append(line)
    text = "\n".join(kept)
    return [statement.strip() for statement in text.split(";") if statement.strip()]


def _ensure_unique_key(cursor, database: str, table: str, key_name: str, columns: str) -> None:
    """旧表可能没有唯一键：先去重，再补索引"""
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = %s AND table_name = %s AND index_name = %s",
        (database, table, key_name),
    )
    if cursor.fetchone()[0] > 0:
        return

    column_list = [column.strip() for column in columns.split(",")]
    join = " AND ".join(f"t1.{column} = t2.{column}" for column in column_list)
    cursor.execute(f"DELETE t1 FROM {table} t1 JOIN {table} t2 ON {join} AND t1.id > t2.id")
    cursor.execute(f"ALTER TABLE {table} ADD UNIQUE KEY {key_name} ({columns})")
    print(f"   已为 {table} 补充唯一索引 {key_name}({columns})")


def init_database() -> None:
    """建库 + 建表 + 种子数据（幂等）"""
    import pymysql

    settings = get_settings()
    connection = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` "
                "DEFAULT CHARACTER SET utf8mb4"
            )
            cursor.execute(f"USE `{settings.db_name}`")

            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            statements = _split_statements(sql)
            # 先建表（前半部分是 CREATE TABLE）
            create_statements = [
                statement for statement in statements
                if statement.lstrip().upper().startswith("CREATE TABLE")
            ]
            insert_statements = [
                statement for statement in statements
                if statement.lstrip().upper().startswith("INSERT")
            ]

            for statement in create_statements:
                cursor.execute(statement)

            for table, (key_name, columns) in UNIQUE_KEYS.items():
                _ensure_unique_key(cursor, settings.db_name, table, key_name, columns)

            for statement in insert_statements:
                cursor.execute(statement)

        print(f"✅ 数据库初始化完成: {settings.db_name}")
    finally:
        connection.close()


if __name__ == "__main__":
    init_database()

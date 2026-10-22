"""MySQL 连接池

设计要点：
1. 懒加载：进程启动时不连库，第一次真正查询才建池，避免 DB 故障拖慢启动。
2. 优雅降级：建池或取连接失败时返回 None，调用方回退到模型估算值，请求不失败。
3. 配置全部来自环境变量（backend/.env），不硬编码账号密码。
"""

import threading
from typing import Optional

from ..config import get_settings

_pool = None
_lock = threading.Lock()
_warned = False


def get_pool():
    """获取（或首次创建）连接池，失败返回 None"""
    global _pool
    if _pool is not None:
        return _pool

    with _lock:
        if _pool is not None:
            return _pool

        settings = get_settings()
        if not settings.db_enabled:
            print("ℹ️ DB_ENABLED=false，预算将使用模型估算值")
            return None

        try:
            import pymysql
            from dbutils.pooled_db import PooledDB

            _pool = PooledDB(
                creator=pymysql,
                maxconnections=5,
                mincached=1,
                blocking=True,
                host=settings.db_host,
                port=settings.db_port,
                user=settings.db_user,
                password=settings.db_password,
                database=settings.db_name,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            print(
                f"✅ MySQL 连接池已创建: "
                f"{settings.db_host}:{settings.db_port}/{settings.db_name}"
            )
        except Exception as exc:  # noqa: BLE001 - 任何异常都不应阻断主流程
            print(f"⚠️ MySQL 连接池创建失败，预算回退到模型估算值: {exc}")
            _pool = None

    return _pool


def get_connection() -> Optional[object]:
    """从池里取一个连接；不可用时返回 None"""
    global _warned
    pool = get_pool()
    if pool is None:
        return None
    try:
        return pool.connection()
    except Exception as exc:  # noqa: BLE001
        if not _warned:
            print(f"⚠️ 获取 MySQL 连接失败，后续查询将回退: {exc}")
            _warned = True
        return None


def reset_pool() -> None:
    """关闭并重置连接池（测试用）"""
    global _pool, _warned
    if _pool is not None:
        try:
            _pool.close()
        except Exception:  # noqa: BLE001
            pass
    _pool = None
    _warned = False

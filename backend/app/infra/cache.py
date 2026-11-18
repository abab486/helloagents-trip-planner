"""可选的 Redis 缓存，没有 Redis 时自动退回进程内内存缓存。

Day 4 故意不把 Redis 设成启动依赖：
    - 配了 REDIS_URL / REDIS_HOST 且能连上 -> RedisCache
    - 否则 -> MemoryCache（进程内、带 TTL）

同一套接口同时服务计划缓存、幂等、限流计数和行程快照，
所以上层代码不用关心当前到底是哪个后端。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# 缓存后端的统一契约：上层只依赖这四个方法，不关心背后是 Redis 还是字典
# 注意没有 set_if_absent（SETNX），所以"先占位再干活"那种严格幂等做不了
class Cache(Protocol):
    backend: str

    # 读 JSON；键不存在或已过期返回 None
    def get_json(self, key: str) -> dict[str, Any] | None:
        ...

    # 写 JSON；ttl_s <= 0 表示永不过期
    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        ...

    # 计数器自增并返回新值；键不存在时先建再返回 1（限流用它）
    def incr(self, key: str, ttl_s: int) -> int:
        ...

    # 删键，键不存在也不报错
    def delete(self, key: str) -> None:
        ...


# 把请求体压成一个短哈希，给缓存 key 用
# sort_keys 是关键：dict 顺序不同也必须算出同一个值，否则幂等永远不命中
# 截前 24 位只为让 key 短一点，这个长度下 sha256 的碰撞概率可以忽略
def hash_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


# 进程内缓存：一个 dict 加一把锁，值存成 JSON 字符串，过期时间用 monotonic 记
# 单 worker 下完全够用；一旦起了多个进程或副本就各存一份，限流和幂等会失真
class MemoryCache:
    backend = "memory"

    def __init__(self) -> None:
        # key -> (过期时间戳 或 None, JSON 字符串)
        self._store: dict[str, tuple[float | None, str]] = {}
        self._lock = threading.Lock()

    # 取原始字符串，顺手把已过期的键删掉（惰性过期，没有后台清理线程）
    # 用 time.monotonic() 而不是 time.time()：系统时间被调整也不会把 TTL 弄乱
    def _get_raw(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at is not None and expires_at <= now:
                self._store.pop(key, None)
                return None
            return value

    # 反序列化放在锁外做，少占着锁
    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._get_raw(key)
        if raw is None:
            return None
        return json.loads(raw)

    # ttl_s <= 0 时记成 None，表示永不过期
    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        expires_at = time.monotonic() + ttl_s if ttl_s > 0 else None
        with self._lock:
            self._store[key] = (expires_at, raw)

    # 计数器：键不存在就建成 1，存在且没过期就 +1
    # 已过期的键走"重建"分支，等价于新窗口从 1 开始；已存在的键不刷新过期时间，是固定窗口
    def incr(self, key: str, ttl_s: int) -> int:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is not None:
                expires_at, raw = item
                if expires_at is None or expires_at > now:
                    value = int(json.loads(raw)) + 1
                    self._store[key] = (expires_at, json.dumps(value))
                    return value
            self._store[key] = (now + ttl_s, "1")
            return 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


# Redis 实现：把同样的语义翻译成 redis 命令，客户端由 create_cache 统一建
# 注意 incr 里每次都会重设 expire，所以 Redis 版的限流窗口会滑动，和 MemoryCache 不一致
class RedisCache:
    backend = "redis"

    def __init__(self, client: Any) -> None:
        self._client = client

    # 取出来是 str（连接时开了 decode_responses），这里再 json.loads
    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    # ex 传 None 表示不过期，和 MemoryCache 的 ttl_s<=0 语义对齐
    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        self._client.set(key, raw, ex=ttl_s if ttl_s > 0 else None)

    # 用 pipeline 把 incr 和 expire 打包成一次往返，避免"自增成功但过期没设上"导致键永不过期
    # 代价是每次自增都续期：只要请求不断，计数永不清零，比固定窗口严格得多
    def incr(self, key: str, ttl_s: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_s)
        count, _ = pipe.execute()
        return int(count)

    def delete(self, key: str) -> None:
        self._client.delete(key)


# 按环境变量挑后端：没配就直接用内存，配了但连不上也退回内存
# 两个刻意的小设计：redis 放在函数内延迟 import（没装包也能启动）、连接超时压到 0.5 秒（不让 Redis 拖慢主流程）
def create_cache() -> Cache:
    url = os.getenv("REDIS_URL", "").strip()
    if not url and os.getenv("REDIS_HOST"):
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = os.getenv("REDIS_PORT", "6379")
        db = os.getenv("REDIS_DB", "0")
        password = os.getenv("REDIS_PASSWORD", "")
        auth = f":{password}@" if password else ""
        url = f"redis://{auth}{host}:{port}/{db}"

    if not url:
        logger.info("REDIS_URL 未配置，使用内存缓存（单进程）")
        return MemoryCache()

    try:
        from redis import Redis

        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        # ping 一次算探活：连不上就在启动阶段暴露，而不是等第一个请求超时
        client.ping()
        logger.info("Redis 缓存已连接")
        return RedisCache(client)
    except Exception as exc:  # noqa: BLE001 - Redis is optional
        # 连不上不算致命：退回内存照样能跑，只是多副本下限流/幂等会失效
        logger.warning("Redis 不可用，回退到内存缓存: %s", exc)
        return MemoryCache()

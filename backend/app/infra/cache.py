"""Optional Redis cache with an in-memory fallback.

Day 4 deliberately does not require Redis to boot:
    - REDIS_URL / REDIS_HOST set + reachable -> RedisCache
    - otherwise -> MemoryCache (process-local, TTL-aware)

The same interface covers plan cache, idempotency, rate limiting and trip
snapshots, so the service code does not care which backend is active.
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


class Cache(Protocol):
    backend: str

    def get_json(self, key: str) -> dict[str, Any] | None:
        ...

    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        ...

    def incr(self, key: str, ttl_s: int) -> int:
        ...

    def delete(self, key: str) -> None:
        ...


def hash_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


class MemoryCache:
    backend = "memory"

    def __init__(self) -> None:
        self._store: dict[str, tuple[float | None, str]] = {}
        self._lock = threading.Lock()

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

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._get_raw(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        expires_at = time.monotonic() + ttl_s if ttl_s > 0 else None
        with self._lock:
            self._store[key] = (expires_at, raw)

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


class RedisCache:
    backend = "redis"

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set_json(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        self._client.set(key, raw, ex=ttl_s if ttl_s > 0 else None)

    def incr(self, key: str, ttl_s: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_s)
        count, _ = pipe.execute()
        return int(count)

    def delete(self, key: str) -> None:
        self._client.delete(key)


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
        client.ping()
        logger.info("Redis 缓存已连接")
        return RedisCache(client)
    except Exception as exc:  # noqa: BLE001 - Redis is optional
        logger.warning("Redis 不可用，回退到内存缓存: %s", exc)
        return MemoryCache()

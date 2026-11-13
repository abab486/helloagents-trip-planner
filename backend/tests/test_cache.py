"""Cache behavior tests: memory backend is the no-Redis fallback."""

import time

from app.infra.cache import MemoryCache, hash_payload


def test_memory_cache_json_roundtrip():
    cache = MemoryCache()
    cache.set_json("k", {"a": 1, "b": "镇江"}, ttl_s=60)
    assert cache.get_json("k") == {"a": 1, "b": "镇江"}
    cache.delete("k")
    assert cache.get_json("k") is None


def test_memory_cache_ttl_expires():
    cache = MemoryCache()
    cache.set_json("k", {"a": 1}, ttl_s=0.01)
    time.sleep(0.02)
    assert cache.get_json("k") is None


def test_memory_cache_incr():
    cache = MemoryCache()
    assert cache.incr("rate", 60) == 1
    assert cache.incr("rate", 60) == 2
    assert cache.incr("rate", 60) == 3


def test_hash_payload_is_stable():
    one = hash_payload({"city": "镇江", "days": 2})
    two = hash_payload({"days": 2, "city": "镇江"})
    assert one == two
    assert len(one) == 24

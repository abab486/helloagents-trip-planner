"""缓存行为测试：内存后端是没有 Redis 时的兜底实现。

这里只测 MemoryCache 和 hash_payload —— Redis 那条路径要真起服务才能验，
CI 里 REDIS_URL 是空的，create_cache 会直接回落到内存。
"""

import time

from app.infra.cache import MemoryCache, hash_payload


# 存进去再读出来，中文不乱码；删掉之后必须读不到
def test_memory_cache_json_roundtrip():
    cache = MemoryCache()
    cache.set_json("k", {"a": 1, "b": "镇江"}, ttl_s=60)
    assert cache.get_json("k") == {"a": 1, "b": "镇江"}
    cache.delete("k")
    assert cache.get_json("k") is None


# TTL 到了就读不到：用 0.01 秒过期 + 睡 0.02 秒，比改系统时间或 mock 时钟都省事
# 注意 MemoryCache 用 time.monotonic()，所以睡多少就是真过期多少
def test_memory_cache_ttl_expires():
    cache = MemoryCache()
    cache.set_json("k", {"a": 1}, ttl_s=0.01)
    time.sleep(0.02)
    assert cache.get_json("k") is None


# incr 就是限流用的计数器：第一次建键返回 1，之后每次 +1
def test_memory_cache_incr():
    cache = MemoryCache()
    assert cache.incr("rate", 60) == 1
    assert cache.incr("rate", 60) == 2
    assert cache.incr("rate", 60) == 3


# 同一份数据换个 key 顺序，哈希必须一样（靠 json.dumps 的 sort_keys）
# 这是幂等能命中的前提：dict 顺序不该影响"是不是同一个请求"
# 长度固定 24 位，是 sha256 截断给缓存 key 留的余量
def test_hash_payload_is_stable():
    one = hash_payload({"city": "镇江", "days": 2})
    two = hash_payload({"days": 2, "city": "镇江"})
    assert one == two
    assert len(one) == 24

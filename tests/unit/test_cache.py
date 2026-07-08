"""CacheManager 单元测试 — 缓存策略。"""

import time

import pytest

from dataworks_agent.cache.manager import CacheManager, get_cache_manager


@pytest.fixture
def cache():
    """创建 CacheManager 实例。"""
    return CacheManager(max_size=100, default_ttl=60)


def test_get_set(cache):
    """测试 get/set。"""
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_get_miss(cache):
    """测试缓存未命中。"""
    result = cache.get("nonexistent")
    assert result is None


def test_set_with_ttl(cache):
    """测试带 TTL 的 set。"""
    cache.set("key1", "value1", ttl=0.1)  # 0.1 秒
    assert cache.get("key1") == "value1"

    # 等待过期
    time.sleep(0.15)
    assert cache.get("key1") is None


def test_delete(cache):
    """测试删除。"""
    cache.set("key1", "value1")
    assert cache.delete("key1") is True
    assert cache.get("key1") is None


def test_delete_nonexistent(cache):
    """测试删除不存在的键。"""
    assert cache.delete("nonexistent") is False


def test_clear(cache):
    """测试清空缓存。"""
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.clear()
    assert cache.size == 0


def test_get_or_set(cache):
    """测试 get_or_set。"""
    # 第一次调用，应该调用工厂函数
    result = cache.get_or_set("key1", lambda: "computed_value")
    assert result == "computed_value"
    assert cache.get("key1") == "computed_value"

    # 第二次调用，应该直接返回缓存值
    result = cache.get_or_set("key1", lambda: "new_value")
    assert result == "computed_value"


def test_lru_eviction(cache):
    """测试 LRU 淘汰。"""
    # 创建小容量缓存
    small_cache = CacheManager(max_size=3, default_ttl=60)

    small_cache.set("key1", "value1")
    small_cache.set("key2", "value2")
    small_cache.set("key3", "value3")

    # 访问 key1，使其最近使用
    small_cache.get("key1")

    # 添加新条目，应该淘汰 key2（最旧）
    small_cache.set("key4", "value4")

    assert small_cache.get("key1") == "value1"  # 最近使用
    assert small_cache.get("key2") is None  # 被淘汰
    assert small_cache.get("key3") == "value3"
    assert small_cache.get("key4") == "value4"


def test_hit_rate(cache):
    """测试命中率。"""
    cache.set("key1", "value1")

    # 命中
    cache.get("key1")
    cache.get("key1")

    # 未命中
    cache.get("nonexistent1")
    cache.get("nonexistent2")

    assert cache.hit_rate == 0.5  # 2 命中 / 4 总计


def test_cleanup_expired(cache):
    """测试清理过期条目。"""
    cache.set("key1", "value1", ttl=0.1)
    cache.set("key2", "value2", ttl=60)

    time.sleep(0.15)

    cleaned = cache.cleanup_expired()
    assert cleaned == 1
    assert cache.size == 1


def test_get_stats(cache):
    """测试获取统计。"""
    cache.set("key1", "value1")
    cache.get("key1")
    cache.get("nonexistent")

    stats = cache.get_stats()
    assert stats["size"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_get_cache_manager():
    """测试获取全局缓存管理器。"""
    manager = get_cache_manager()
    assert isinstance(manager, CacheManager)

    # 应该返回同一个实例
    manager2 = get_cache_manager()
    assert manager is manager2

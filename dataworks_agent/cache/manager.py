"""CacheManager — 缓存策略管理。

实现缓存功能：
1. 内存缓存（LRU）
2. TTL 过期
3. 缓存统计
4. 事件驱动缓存失效
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.cache.events import Event, EventType, get_event_bus


@dataclass
class CacheEntry:
    """缓存条目。"""

    key: str
    value: Any
    created_at: float
    ttl: float  # 秒
    tags: list[str] = field(default_factory=list)  # 标签，用于按标签失效
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        """检查是否过期。"""
        return time.time() - self.created_at > self.ttl


class CacheManager:
    """缓存管理器 — 内存 LRU 缓存。

    特性：
    - LRU 淘汰策略
    - TTL 过期
    - 线程安全
    - 缓存统计
    - 事件驱动缓存失效
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300):
        """
        初始化缓存管理器。

        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认 TTL（秒）
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.RLock()

        # 统计
        self._hits = 0
        self._misses = 0

        # 订阅缓存失效事件
        self._setup_event_subscriptions()

    def get(self, key: str) -> Any | None:
        """获取缓存值。"""
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired:
                # 过期，删除
                del self._cache[key]
                self._misses += 1
                return None

            # 命中，移到末尾（LRU）
            self._cache.move_to_end(key)
            entry.access_count += 1
            self._hits += 1

            return entry.value

    def set(
        self, key: str, value: Any, ttl: float | None = None, tags: list[str] | None = None
    ) -> None:
        """设置缓存值。"""
        if ttl is None:
            ttl = self._default_ttl

        with self._lock:
            # 如果已存在，删除旧条目
            if key in self._cache:
                del self._cache[key]

            # 检查容量
            if len(self._cache) >= self._max_size:
                # 淘汰最旧的
                self._cache.popitem(last=False)

            # 添加新条目
            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl,
                tags=tags or [],
            )

    def delete(self, key: str) -> bool:
        """删除缓存条目。"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._cache.clear()

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: float | None = None,
    ) -> Any:
        """获取缓存值，不存在则调用工厂函数生成。"""
        value = self.get(key)
        if value is not None:
            return value

        value = factory()
        self.set(key, value, ttl)
        return value

    @property
    def size(self) -> int:
        """当前缓存大小。"""
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        """缓存命中率。"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计。"""
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
        }

    def cleanup_expired(self) -> int:
        """清理过期条目。"""
        with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    def _setup_event_subscriptions(self) -> None:
        """设置事件订阅。"""
        event_bus = get_event_bus()
        event_bus.subscribe(EventType.CACHE_INVALIDATE, self._handle_invalidate_event)

    def _handle_invalidate_event(self, event: Event) -> None:
        """处理缓存失效事件。"""
        source = event.source
        pattern = event.data.get("pattern") if event.data else None

        if pattern:
            # 按模式失效
            self.invalidate_by_pattern(pattern)
        elif source:
            # 按来源失效（支持通配符）
            self.invalidate_by_source(source)

    def invalidate_by_pattern(self, pattern: str) -> int:
        """按模式失效缓存。

        Args:
            pattern: 正则表达式模式

        Returns:
            失效的条目数
        """
        with self._lock:
            regex = re.compile(pattern)
            keys_to_delete = [key for key in self._cache if regex.match(key)]
            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)

    def invalidate_by_source(self, source: str) -> int:
        """按来源失效缓存。

        Args:
            source: 来源（支持 * 通配符）

        Returns:
            失效的条目数
        """
        with self._lock:
            if "*" in source:
                # 通配符匹配
                prefix = source.replace("*", "")
                keys_to_delete = [key for key in self._cache if key.startswith(prefix)]
            else:
                # 精确匹配
                keys_to_delete = [
                    key for key in self._cache if key == source or key.startswith(f"{source}:")
                ]

            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)

    def invalidate_by_tags(self, tags: list[str]) -> int:
        """按标签失效缓存。

        Args:
            tags: 标签列表

        Returns:
            失效的条目数
        """
        with self._lock:
            keys_to_delete = [
                key for key, entry in self._cache.items() if any(tag in entry.tags for tag in tags)
            ]
            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)

    def publish_invalidation(self, source: str, pattern: str | None = None) -> None:
        """发布缓存失效事件。"""
        event_bus = get_event_bus()
        event = Event(
            event_type=EventType.CACHE_INVALIDATE,
            source=source,
            data={"pattern": pattern} if pattern else None,
        )
        event_bus.publish(event)


# 全局缓存实例
_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """获取全局缓存管理器。"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

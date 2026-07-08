"""Cache Events — 缓存失效通知机制。

实现事件驱动的缓存失效：
1. 事件总线
2. 缓存失效订阅
3. 自动缓存清理
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """事件类型。"""

    CACHE_INVALIDATE = "cache_invalidate"  # 缓存失效
    CACHE_REFRESH = "cache_refresh"  # 缓存刷新
    DATA_UPDATE = "data_update"  # 数据更新
    TASK_STATUS_CHANGED = "task_status_changed"  # 建模任务状态转移（dashboard WS 推送源）


@dataclass
class Event:
    """事件。"""

    event_type: EventType
    source: str  # 事件来源（table_name / api_name / etc.）
    data: dict[str, Any] | None = None


class EventBus:
    """事件总线 — 发布/订阅模式。"""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Callable]] = {}

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """订阅事件。"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """取消订阅。"""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)

    def publish(self, event: Event) -> None:
        """发布事件。"""
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error("事件处理失败: %s", e)

    async def publish_async(self, event: Event) -> None:
        """异步发布事件。"""
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    if callable(callback):
                        result = callback(event)
                        if hasattr(result, "__await__"):
                            await result
                except Exception as e:
                    logger.error("事件处理失败: %s", e)


# 全局事件总线
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局事件总线。"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus

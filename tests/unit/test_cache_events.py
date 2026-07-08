"""Cache Events 单元测试 — 缓存失效通知机制。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.cache.events import Event, EventBus, EventType, get_event_bus
from dataworks_agent.cache.manager import CacheManager, get_cache_manager


@pytest.fixture
def event_bus():
    """创建 EventBus 实例。"""
    return EventBus()


@pytest.fixture
def cache():
    """创建 CacheManager 实例。"""
    return CacheManager(max_size=100, default_ttl=60)


def test_event_bus_subscribe(event_bus):
    """订阅事件。"""
    received_events = []

    def handler(event):
        received_events.append(event)

    event_bus.subscribe(EventType.CACHE_INVALIDATE, handler)

    # 发布事件
    event = Event(event_type=EventType.CACHE_INVALIDATE, source="test")
    event_bus.publish(event)

    assert len(received_events) == 1
    assert received_events[0].source == "test"


def test_event_bus_unsubscribe(event_bus):
    """取消订阅。"""
    received_events = []

    def handler(event):
        received_events.append(event)

    event_bus.subscribe(EventType.CACHE_INVALIDATE, handler)
    event_bus.unsubscribe(EventType.CACHE_INVALIDATE, handler)

    # 发布事件
    event = Event(event_type=EventType.CACHE_INVALIDATE, source="test")
    event_bus.publish(event)

    assert len(received_events) == 0


def test_cache_invalidate_by_pattern(cache):
    """按模式失效缓存。"""
    cache.set("tasks:123", "value1")
    cache.set("tasks:456", "value2")
    cache.set("dashboard", "value3")

    # 按模式失效
    count = cache.invalidate_by_pattern(r"^tasks:.*")
    assert count == 2
    assert cache.get("tasks:123") is None
    assert cache.get("tasks:456") is None
    assert cache.get("dashboard") == "value3"


def test_cache_invalidate_by_source(cache):
    """按来源失效缓存。"""
    cache.set("tasks:123", "value1")
    cache.set("tasks:456", "value2")
    cache.set("dashboard", "value3")

    # 按来源失效（支持通配符）
    count = cache.invalidate_by_source("tasks*")
    assert count == 2
    assert cache.get("tasks:123") is None
    assert cache.get("dashboard") == "value3"


def test_cache_invalidate_by_tags(cache):
    """按标签失效缓存。"""
    cache.set("key1", "value1", tags=["tasks"])
    cache.set("key2", "value2", tags=["dashboard"])
    cache.set("key3", "value3", tags=["tasks", "important"])

    # 按标签失效
    count = cache.invalidate_by_tags(["tasks"])
    assert count == 2
    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    assert cache.get("key3") is None


def test_cache_publish_invalidation(cache):
    """发布缓存失效事件。"""
    received_events = []

    def handler(event):
        received_events.append(event)

    event_bus = get_event_bus()
    event_bus.subscribe(EventType.CACHE_INVALIDATE, handler)

    # 发布失效事件
    cache.publish_invalidation("tasks")

    assert len(received_events) == 1
    assert received_events[0].source == "tasks"


def test_cache_auto_invalidate_on_event(cache):
    """事件触发自动失效。"""
    cache.set("tasks:123", "value1")
    cache.set("tasks:456", "value2")

    # 通过事件总线发布失效事件
    event_bus = get_event_bus()
    event = Event(
        event_type=EventType.CACHE_INVALIDATE,
        source="tasks",
        data={"pattern": r"^tasks:.*"},
    )
    event_bus.publish(event)

    # 验证缓存已失效
    assert cache.get("tasks:123") is None
    assert cache.get("tasks:456") is None


def test_get_event_bus():
    """获取全局事件总线。"""
    bus = get_event_bus()
    assert isinstance(bus, EventBus)

    # 应该返回同一个实例
    bus2 = get_event_bus()
    assert bus is bus2


def test_get_cache_manager():
    """获取全局缓存管理器。"""
    manager = get_cache_manager()
    assert isinstance(manager, CacheManager)

    # 应该返回同一个实例
    manager2 = get_cache_manager()
    assert manager is manager2


@pytest.mark.asyncio
async def test_event_bus_publish_async(event_bus):
    """异步发布事件。"""
    received_events = []

    def handler(event):
        received_events.append(event)

    event_bus.subscribe(EventType.CACHE_INVALIDATE, handler)

    # 异步发布
    await event_bus.publish_async(Event(event_type=EventType.CACHE_INVALIDATE, source="test"))

    assert len(received_events) == 1


def test_task_status_changed_enum_exists():
    """v10：TASK_STATUS_CHANGED 枚举已添加，供 dashboard WS 推送使用。"""
    assert EventType.TASK_STATUS_CHANGED.value == "task_status_changed"


@pytest.mark.asyncio
async def test_monitor_ws_subscribed_to_task_status_changed():
    """monitor WS 端点启动时已订阅 TASK_STATUS_CHANGED，确保状态变更触发推送。

    行为级断言：通过全局 EventBus publish_async，观察 _ws_clients 是否被 fanout。
    """
    from dataworks_agent.routers.monitor import _ws_clients

    fake_ws = MagicMock()
    fake_ws.send_text = AsyncMock()
    _ws_clients.add(fake_ws)
    try:
        await get_event_bus().publish_async(
            Event(
                event_type=EventType.TASK_STATUS_CHANGED,
                source="task_subscription_check",
                data={
                    "task_id": "task_subscription_check",
                    "status": "running",
                    "timestamp": "2026-07-07T10:00:00Z",
                },
            )
        )
        # publish_async 已经 await 所有 async handler；fake_ws.send_text 应该被调用
        assert fake_ws.send_text.await_count >= 1, (
            "publish_async 后 WS 客户端必须收到 fanout；若失败说明 monitor 未订阅 TASK_STATUS_CHANGED"
        )
    finally:
        _ws_clients.discard(fake_ws)

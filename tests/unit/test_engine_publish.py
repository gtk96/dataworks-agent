"""ModelingEngine 状态发布护栏 — R17 dashboard 实时刷新修复。

覆盖：engine 写 t.status 后必须 publish TASK_STATUS_CHANGED，
驱动 dashboard WS 实时刷新 + cache 失效。

这些测试不依赖完整 DB 集成（用 mock），只验证 status → publish 链路完整性。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from dataworks_agent.cache.events import Event, EventType, get_event_bus

# ───────────────────────────────────────────────────────────
# _publish_task_status helper 自身
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_task_status_publishes_event() -> None:
    """_publish_task_status 必须 publish TASK_STATUS_CHANGED 事件含正确字段。"""
    from dataworks_agent.modeling.engine import _publish_task_status

    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus = get_event_bus()
    saved_subs = event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy()
    for cb in saved_subs:
        event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
    event_bus.subscribe(EventType.TASK_STATUS_CHANGED, lambda e: asyncio.create_task(_capture(e)))
    try:
        await _publish_task_status("task_x", "running")
        await asyncio.sleep(0.05)

        relevant = [e for e in captured if e.data.get("task_id") == "task_x"]
        assert len(relevant) == 1
        evt = relevant[0]
        assert evt.event_type == EventType.TASK_STATUS_CHANGED
        assert evt.data["task_id"] == "task_x"
        assert evt.data["status"] == "running"
        assert "timestamp" in evt.data
    finally:
        for cb in event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy():
            event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
        for cb in saved_subs:
            event_bus.subscribe(EventType.TASK_STATUS_CHANGED, cb)


@pytest.mark.asyncio
async def test_publish_task_status_swallows_exceptions() -> None:
    """publish 失败不应抛 — 主链路不应被监控推送拖死。"""
    from dataworks_agent.modeling.engine import _publish_task_status

    # 故意把 publish_async 替换成会抛的版本
    bus = get_event_bus()
    saved_subs = bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy()

    async def _boom(_event: Event) -> None:
        raise RuntimeError("simulated publish failure")

    for cb in saved_subs:
        bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
    bus.subscribe(EventType.TASK_STATUS_CHANGED, _boom)
    try:
        # 不应抛
        await _publish_task_status("task_y", "completed")
    finally:
        for cb in bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy():
            bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
        for cb in saved_subs:
            bus.subscribe(EventType.TASK_STATUS_CHANGED, cb)


# ───────────────────────────────────────────────────────────
# engine 写 status 路径必须 publish（用 mock 隔离 DB）
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_create_task_publishes_pending():
    """engine.create_task 同步写 PENDING 后必须 publish TASK_STATUS_CHANGED。

    R17 修复前这是漏点：create_task 写完 DB 没调 publish，dashboard 60s 内看不到新任务。
    """
    from dataworks_agent.modeling.engine import ModelingEngine
    from dataworks_agent.schemas import (
        CreateTaskRequest,
        CycleType,
        DataLayer,
        UpdateMethod,
    )

    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus = get_event_bus()
    saved_subs = event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy()
    for cb in saved_subs:
        event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
    event_bus.subscribe(EventType.TASK_STATUS_CHANGED, lambda e: asyncio.create_task(_capture(e)))

    try:
        engine = ModelingEngine()
        req = CreateTaskRequest(
            source_table="ods_test_src",
            target_layer=DataLayer.DWD,
            domain="test",
            entity="entity",
            update_method=UpdateMethod.DAY,
            schedule_type=CycleType.DAILY,
        )
        # mock SessionLocal + ddl_gen.generate（DWD dry_run 路径不需要真实 DB）

        mock_model = MagicMock()
        mock_model.task_id = "task_test_xxx"
        mock_model.target_table = "dwd_test_entity_daily"

        with (
            patch("dataworks_agent.db.database.SessionLocal") as mock_session_local,
        ):
            mock_db = MagicMock()
            mock_session_local.return_value.__enter__.return_value = mock_db
            mock_session_local.return_value.__exit__.return_value = False
            mock_db.add = MagicMock()
            mock_db.commit = MagicMock()

            with patch("dataworks_agent.modeling.engine.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value.hex = "abcdef123456789012"
                task_id = await engine.create_task(req, client_ip="127.0.0.1")

        assert task_id == "task_abcdef123456"
        await asyncio.sleep(0.1)

        # 验证 PENDING 已 publish
        relevant = [e for e in captured if e.data.get("task_id") == task_id]
        assert len(relevant) >= 1, f"create_task 应至少 publish 1 个事件，实获 {captured}"
        assert relevant[0].data["status"] == "pending", (
            f"首次 publish 必须是 pending，实获 {relevant[0].data['status']}"
        )
    finally:
        for cb in event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy():
            event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
        for cb in saved_subs:
            event_bus.subscribe(EventType.TASK_STATUS_CHANGED, cb)


# ───────────────────────────────────────────────────────────
# WS broadcast → cache.delete("dashboard") 链路（已有 test_dashboard_cache 覆盖）
# 这里只验证 publish 路径与 dashboard WS 联动
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_to_dashboard_cache_invalidation_pipeline():
    """publish TASK_STATUS_CHANGED → _broadcast_task_status → cache.delete("dashboard")。

    端到端验证 R17 修复后的链路完整性：
    engine publish → EventBus → monitor WS handler → cache.delete("dashboard")。
    """
    from dataworks_agent.routers.monitor import _broadcast_task_status

    cache_mock = MagicMock()
    cache_mock.delete = MagicMock(return_value=True)
    cache_mock.invalidate_by_source = MagicMock(return_value=1)

    with patch("dataworks_agent.cache.get_cache_manager", return_value=cache_mock):
        event = Event(
            event_type=EventType.TASK_STATUS_CHANGED,
            source="task",
            data={"task_id": "task_z", "status": "running", "timestamp": "2026-07-07T10:00:00Z"},
        )
        await _broadcast_task_status(event)

    cache_mock.delete.assert_called_once_with("dashboard")

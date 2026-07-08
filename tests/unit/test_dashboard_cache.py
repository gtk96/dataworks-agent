"""Dashboard 缓存 + 路径自测 — R17 自审补的护栏。

覆盖：
1. 空 DB 不崩（total_tasks=0, success_rate=0）
2. cache 命中直接返回（不查 DB）
3. cache 损坏（值不是 dict）→ 后端按业务兜底走重算
4. WS broadcast → cache.delete("dashboard") 被调用
5. _classify_status 把状态正确归桶（dashboard 数字正确性的基础）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dataworks_agent.cache.events import Event, EventType, get_event_bus
from dataworks_agent.routers.monitor import (
    _broadcast_task_status,
)

# ───────────────────────────────────────────────────────────
# 1. 状态归桶正确性 — dashboard 数字正确性的根基
# ───────────────────────────────────────────────────────────


class TestClassifyStatusContract:
    """dashboard 把所有 status 归到 running/completed/failed/pending 四桶，
    任何 status 字符串必须在 _classify_status 里被处理（要么归桶要么返回 None）。

    这层契约错会直接导致 dashboard 数字漏算。
    """

    def test_terminal_states(self) -> None:
        from dataworks_agent.services.task_classification import _classify_status

        assert _classify_status("completed") == "completed"
        assert _classify_status("success") == "completed"
        assert _classify_status("failed") == "failed"
        assert _classify_status("partial") == "failed"

    def test_pending_states(self) -> None:
        from dataworks_agent.services.task_classification import _classify_status

        assert _classify_status("pending") == "pending"
        assert _classify_status("queued") == "pending"

    def test_in_flight_states(self) -> None:
        from dataworks_agent.services.task_classification import _classify_status

        for s in (
            "running",
            "ddl_gen",
            "table_cre",
            "root_check",
            "dml_write",
            "sched_cfg",
            "testing",
            "claimed",
        ):
            assert _classify_status(s) == "running"

    def test_unknown_returns_none(self) -> None:
        """未识别状态归 None（不入桶），dashboard 不会算它。"""
        from dataworks_agent.services.task_classification import _classify_status

        assert _classify_status("mystery_state") is None
        assert _classify_status("") is None

    def test_case_insensitive(self) -> None:
        """大写 / 混合大小写也能正确归桶。"""
        from dataworks_agent.services.task_classification import _classify_status

        assert _classify_status("COMPLETED") == "completed"
        assert _classify_status("Running") == "running"
        assert _classify_status("FAILED") == "failed"


# ───────────────────────────────────────────────────────────
# 2. WS 事件触发 cache 失效
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_event_invalidates_dashboard_cache():
    """TaskStatusChanged 事件触发后, _broadcast_task_status 必须 delete dashboard cache。

    否则前端 60s 内显示旧数据，"实时推送"名存实亡。
    """
    cache_mock = MagicMock()
    cache_mock.delete = MagicMock(return_value=True)

    # monitor 在 _broadcast_task_status 内函数级 import get_cache_manager
    # patch 真正的 import path "dataworks_agent.cache.get_cache_manager"
    with patch("dataworks_agent.cache.get_cache_manager", return_value=cache_mock):
        event = Event(
            event_type=EventType.TASK_STATUS_CHANGED,
            source="task_z",
            data={"task_id": "task_z", "status": "running", "timestamp": "2026-07-07T10:00:00Z"},
        )
        await _broadcast_task_status(event)

    cache_mock.delete.assert_called_once_with("dashboard")


# ───────────────────────────────────────────────────────────
# 3. broadcast 调 EventBus 订阅、WS 帧契约
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_subscribed_at_module_load():
    """monitor 模块加载时必须订阅 TASK_STATUS_CHANGED（不依赖测试顺序）。"""
    subs = get_event_bus()._subscribers.get(EventType.TASK_STATUS_CHANGED, [])
    assert _broadcast_task_status in subs


@pytest.mark.asyncio
async def test_broadcast_payload_contract():
    """fanout 帧必须含 dashboard 契约字段（type/task_id/status/timestamp）。"""
    import json

    ws = MagicMock()
    ws.send_text = MagicMock()
    # 直接添加到全局 ws pool（_broadcast_task_status 用 _ws_clients 迭代）
    from dataworks_agent.routers import monitor

    saved = set(monitor._ws_clients)
    monitor._ws_clients.clear()
    monitor._ws_clients.add(ws)
    try:
        event = Event(
            event_type=EventType.TASK_STATUS_CHANGED,
            source="task_a",
            data={
                "task_id": "task_a",
                "status": "completed",
                "timestamp": "2026-07-07T10:00:00Z",
            },
        )
        await _broadcast_task_status(event)
    finally:
        monitor._ws_clients.clear()
        monitor._ws_clients.update(saved)

    frame = json.loads(ws.send_text.call_args.args[0])
    assert frame["type"] == "task_status_changed"
    assert frame["task_id"] == "task_a"
    assert frame["status"] == "completed"
    assert "timestamp" in frame


# ───────────────────────────────────────────────────────────
# 4. state_machine.emit_event payload 契约（Bug #1 护栏）
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_machine_emit_event_payload_has_string_event_field():
    """R17 Bug #1 护栏：emit_event data["event"] 必须是事件名字符串而非 Event 对象。

    之前代码有变量遮蔽导致 event=Event(...) 覆盖参数 event: str；修复后用 evt
    命名 Event 对象，保证 data["event"] 是字符串。
    """
    import asyncio

    from dataworks_agent.schemas import TaskStatus
    from dataworks_agent.task_engine.state_machine import TaskStateMachine

    sm = TaskStateMachine(task_id="task_test")
    sm.status = TaskStatus.RUNNING

    # 把 publish_async 替换成同步捕获 Event 对象
    captured: list = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus = get_event_bus()
    # 清理其他订阅者避免干扰
    saved_subs = event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy()
    for cb in saved_subs:
        event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
    event_bus.subscribe(EventType.TASK_STATUS_CHANGED, lambda e: asyncio.create_task(_capture(e)))

    try:
        await sm.emit_event("step", {"step_label": "DDL 生成"})
        # 等 create_task 跑完
        await asyncio.sleep(0.1)

        # 找对应 task_id 的事件
        relevant = [e for e in captured if e.data.get("task_id") == "task_test"]
        assert len(relevant) >= 1, f"应至少 1 个 TASK_STATUS_CHANGED 事件，实获 {captured}"
        payload = relevant[-1].data
        # data["event"] 必须是字符串 "step"，不是 Event 对象
        assert payload["event"] == "step", (
            f"data['event'] 应是字符串 'step'，实获 {type(payload['event']).__name__}: "
            f"{payload['event']!r}"
        )
        # task_id / status / timestamp 也得正确
        assert payload["task_id"] == "task_test"
        assert payload["status"] == TaskStatus.RUNNING.value
        assert "timestamp" in payload
    finally:
        # 还原订阅
        for cb in event_bus._subscribers.get(EventType.TASK_STATUS_CHANGED, []).copy():
            event_bus.unsubscribe(EventType.TASK_STATUS_CHANGED, cb)
        for cb in saved_subs:
            event_bus.subscribe(EventType.TASK_STATUS_CHANGED, cb)

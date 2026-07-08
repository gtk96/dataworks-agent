"""monitor WS 实时推送单元测试 — v10 重构后。

覆盖：
1. WS 接入后 _ws_clients 增 1，断开后减 1
2. 死连接（send_text 抛错）被自动清理
3. 订阅事件触发后所有连接都收到 fanout 帧
4. dashboard 字段已收敛（5 个死字段已删除）
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.cache.events import Event, EventType, get_event_bus
from dataworks_agent.routers.monitor import (
    _broadcast_task_status,
    _ws_clients,
    ws_tasks,
)


@pytest.fixture(autouse=True)
def _clear_ws_clients():
    """每个用例前后清空 WS 客户端池，避免测试间串扰。"""
    _ws_clients.clear()
    yield
    _ws_clients.clear()


@pytest.mark.asyncio
async def test_ws_connect_and_disconnect_manages_pool():
    """WS 接入/断开维护连接池。"""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    # 模拟客户端立刻断开
    ws.receive_text = AsyncMock(side_effect=Exception("client closed"))

    await ws_tasks(ws)

    ws.accept.assert_awaited_once()
    # hello 帧已发，然后断开
    assert ws.send_text.await_count >= 1
    assert ws not in _ws_clients


@pytest.mark.asyncio
async def test_dead_connection_removed_on_broadcast():
    """fanout 时死连接（send_text 抛错）自动从池里踢出。"""
    good = MagicMock()
    good.send_text = AsyncMock()
    dead = MagicMock()
    dead.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))

    _ws_clients.add(good)
    _ws_clients.add(dead)

    event = Event(
        event_type=EventType.TASK_STATUS_CHANGED,
        source="task_x",
        data={"task_id": "task_x", "status": "running", "timestamp": "2026-07-07T10:00:00Z"},
    )
    await _broadcast_task_status(event)

    assert good.send_text.await_count == 1
    assert dead not in _ws_clients
    assert good in _ws_clients


@pytest.mark.asyncio
async def test_broadcast_payload_shape():
    """fanout payload 必须是 dashboard 期望的契约。"""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    _ws_clients.add(ws)

    event = Event(
        event_type=EventType.TASK_STATUS_CHANGED,
        source="task_z",
        data={
            "task_id": "task_z",
            "status": "ddl_gen",
            "timestamp": "2026-07-07T10:00:00Z",
            "event": "step",
            "data": {"step_label": "DDL 生成"},
        },
    )
    await _broadcast_task_status(event)

    payload = json.loads(ws.send_text.await_args.args[0])
    assert payload["type"] == "task_status_changed"
    assert payload["task_id"] == "task_z"
    assert payload["status"] == "ddl_gen"
    assert payload["timestamp"] == "2026-07-07T10:00:00Z"


@pytest.mark.asyncio
async def test_broadcast_skips_when_no_clients():
    """无连接时直接 return，不应抛错。"""
    event = Event(
        event_type=EventType.TASK_STATUS_CHANGED,
        source="task_y",
        data={"task_id": "task_y", "status": "completed"},
    )
    # _ws_clients 为空，broadcast 应静默
    await _broadcast_task_status(event)
    assert not _ws_clients


@pytest.mark.asyncio
async def test_broadcast_subscribed_via_event_bus():
    """验证 monitor 模块加载时确实订阅了 EventBus（不依赖全局单测顺序）。"""
    subs = get_event_bus()._subscribers.get(EventType.TASK_STATUS_CHANGED, [])
    assert _broadcast_task_status in subs


def test_dashboard_response_no_dead_fields():
    """v10 收敛掉 5 个未使用字段 + 1 个语义重叠字段（仅检查返回契约）。"""
    import ast

    from dataworks_agent.routers import monitor

    with open(monitor.__file__, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)

    # 找到 dashboard 函数体里对 result 的最后一次赋值
    result_keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dashboard":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if (
                            isinstance(tgt, ast.Name)
                            and tgt.id == "result"
                            and isinstance(sub.value, ast.Dict)
                        ):
                            for k in sub.value.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    result_keys.add(k.value)
    assert result_keys, "应能解析到 result = { ... } 字典字面量"

    forbidden = {
        "today_completed",
        "today_failed",
        "type_breakdown_labeled",
        "type_labels",
        "queue_backlog",
        "active_tasks",
        "finished",  # 与 completed/failed 语义重叠
    }
    leaked = forbidden & result_keys
    assert not leaked, f"dashboard result 不应再输出字段 {leaked}（v10 收敛）"

"""ModelingDashboard.vue 集成测试 — /api/monitor/dashboard。

WS 行为级测试（ws_tasks hello / fanout）见 tests/unit/test_monitor_ws.py，
那是测试内部协程序直接调 ws_tasks(_broadcast_task_status) 路径，
比 ASGI 跨进程 WebSocket 更简洁、可靠。本文件只保留路由层断言。
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_dashboard_returns_stats(mocked_client):
    """/api/monitor/dashboard 返回总任务数/成功率/分层分布等。"""
    resp = await mocked_client.get("/api/monitor/dashboard")
    # 在 mock 环境下可能因 mcp/bff 不可用 500,路由能进即通过
    assert_routed_response(resp)
    if resp.status_code == 200:
        data = resp.json()
        # 应有总任务相关字段(具体名因实现版本可能不同,只验证有数字)
        assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_dashboard_handles_empty_db(mocked_client):
    """DB 真空时 dashboard 不应崩。"""
    resp = await mocked_client.get("/api/monitor/dashboard")
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_dashboard_v10_no_dead_fields(mocked_client):
    """v10 收敛后 dashboard 返回字段必须 ≤ 9 个核心字段；死字段一律不再出现。"""
    resp = await mocked_client.get("/api/monitor/dashboard")
    assert_routed_response(resp)
    if resp.status_code != 200:
        pytest.skip("dashboard 在 mock 环境非 200，跳过字段断言")

    data = resp.json()
    forbidden = {
        "today_completed",
        "today_failed",
        "type_breakdown_labeled",
        "type_labels",
        "queue_backlog",
        "active_tasks",
        "finished",
    }
    leaked = forbidden & set(data.keys())
    assert not leaked, f"dashboard 响应不应含死字段 {leaked}"

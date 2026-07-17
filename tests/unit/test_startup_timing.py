"""Startup timing test — 验证启动优化效果。

运行方式:
    uv run python -m tests.unit.test_startup_timing

预期结果:
    启动时间 < 10s（优化前 60-75s）
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


def test_import_fast():
    """导入模块的时间应 < 2s。"""
    t0 = time.perf_counter()
    from dataworks_agent.main import create_app

    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"模块导入耗时 {elapsed:.1f}s，超过 2s 阈值"


def test_app_creation_fast():
    """创建 FastAPI 应用实例的时间应 < 3s。"""
    t0 = time.perf_counter()
    from dataworks_agent.main import create_app

    app = create_app()
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"应用创建耗时 {elapsed:.1f}s，超过 3s 阈值"
    assert app is not None
    assert len(app.routes) > 20, f"路由数量异常: {len(app.routes)}"


@pytest.mark.asyncio
async def test_lazy_mcp_compatible_with_system_health():
    """验证 LazyMCPClient 兼容 system.py 的健康检查逻辑。"""
    from dataworks_agent.runtime.lazy_mcp import LazyMCPClient
    from dataworks_agent.state import app_state

    app_state._official_mcp_client = LazyMCPClient()
    official_mcp = getattr(app_state, "_official_mcp_client", None)

    # system.py 中的检查方式
    official_connected = bool(
        official_mcp is not None and getattr(official_mcp.status, "connected", False)
    )
    assert official_connected is False  # 未连接时应为 False

    # workflow_service.py 中的 to_dict() 检查
    status_dict = official_mcp.status.to_dict()
    assert "connected" in status_dict
    assert "error" in status_dict
    assert status_dict["connected"] is False


@pytest.mark.asyncio
async def test_lazy_mcp_has_all_compat_properties():
    """验证 LazyMCPClient 有所有兼容属性。"""
    from dataworks_agent.runtime.lazy_mcp import LazyMCPClient

    lazy = LazyMCPClient()

    # 必需属性
    assert hasattr(lazy, "connected")
    assert hasattr(lazy, "status")
    assert hasattr(lazy, "connect_error")
    assert hasattr(lazy, "connect")
    assert hasattr(lazy, "call_tool")
    assert hasattr(lazy, "list_tools")
    assert hasattr(lazy, "close")
    assert hasattr(lazy, "warmup")

    # status 对象必需属性
    status = lazy.status
    assert hasattr(status, "connected")
    assert hasattr(status, "error")
    assert hasattr(status, "tool_count")
    assert hasattr(status, "tools")
    assert hasattr(status, "to_dict")

    await lazy.close()

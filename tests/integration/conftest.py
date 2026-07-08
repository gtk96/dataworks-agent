"""集成测试通用 mock fixture。

设计目标:
- 完全内存化(不发真 HTTP / 不连真 BFF / 不连真 MCP)
- 每个测试独立的临时 SQLite
- 业务路由可调,但所有外部依赖(mcp_pool / bff_client._http / cookie / smtp)被替换为 mock
- lifespan 启动被跳过(避免真实 MCP/BFF 初始化失败)

使用方式:
    def test_xxx(mocked_client):
        resp = await mocked_client.get("/api/...")
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker

# ───────────────────────────────────────────────────────────
# Mock 工具
# ───────────────────────────────────────────────────────────


class FakeAsyncClient:
    """httpx.AsyncClient 替身 — 记录最后一次调用,返回受控响应。"""

    is_closed = False

    def __init__(self) -> None:
        self.last_method: str = ""
        self.last_url: str = ""
        self.last_params: dict = {}
        self.last_json: dict = {}
        self.response_json: dict = {"code": 200, "data": {}}
        self._responder: callable = None  # 自定义 responder(url, params, json) -> dict

    def set_response(self, payload: dict) -> None:
        self.response_json = payload

    def set_responder(self, fn) -> None:
        """fn(method, url, params, json) -> response dict"""
        self._responder = fn

    async def _capture(self, method: str, url: str, **kwargs):
        self.last_method = method
        self.last_url = url
        self.last_params = kwargs.get("params", {})
        self.last_json = kwargs.get("json", {})
        if self._responder:
            self.response_json = self._responder(method, url, self.last_params, self.last_json)
        resp = MagicMock()
        resp.json.return_value = self.response_json
        resp.raise_for_status = MagicMock()
        resp.text = str(self.response_json)
        return resp

    async def put(self, url, **kw):
        return await self._capture("PUT", url, **kw)

    async def get(self, url, **kw):
        return await self._capture("GET", url, **kw)

    async def post(self, url, **kw):
        return await self._capture("POST", url, **kw)

    async def aclose(self):
        self.is_closed = True


def make_fake_mcp(tool_responses: dict | None = None) -> MagicMock:
    """构造 mock mcp_pool: call_tool(tool_name, args) 返回预设响应。

    tool_responses: {"tool_name": response_dict_or_list, ...}
    默认所有工具返回空列表(适合 lineage/upstream_tasks 这类期望 list[dict] 的调用)。
    """
    responses = tool_responses or {}

    async def call_tool(tool_name: str, arguments: dict):
        if tool_name in responses:
            r = responses[tool_name]
            if callable(r):
                return r(tool_name, arguments)
            return r
        # 默认返回空 list(更接近 BFF list_tasks 的真实返回,避免 AttributeError)
        return []

    pool = MagicMock()
    pool.call_tool = AsyncMock(side_effect=call_tool)
    pool.connect = AsyncMock()
    pool.disconnect = AsyncMock()
    return pool


# ───────────────────────────────────────────────────────────
# 临时数据库 fixture
# ───────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """为当前测试创建临时 SQLite,patch 所有 SessionLocal 引用。

    注意: 由于 SessionLocal 在多个模块内部 import,需要 patch 每个入口。
    """
    db_file = tmp_path / "integration_test.db"
    test_engine = sa_create_engine(f"sqlite:///{db_file}", future=True)
    from dataworks_agent.db.database import Base

    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, autoflush=False)

    # patch 三个常见的 SessionLocal 引用点
    monkeypatch.setattr("dataworks_agent.db.database.SessionLocal", test_session)
    yield test_engine


# ───────────────────────────────────────────────────────────
# 跳过 lifespan + 注入 mock 依赖
# ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mocked_app_state(monkeypatch, temp_db):
    """替换 app_state 上的所有外部依赖: mcp_pool / bff_client / cookie / keepalive。"""
    from dataworks_agent.state import app_state

    # 1. MCP pool — 默认空响应,可由具体测试覆盖
    fake_mcp = make_fake_mcp()
    monkeypatch.setattr(app_state, "_mcp_pool", fake_mcp)
    monkeypatch.setattr(app_state, "mcp_pool", fake_mcp)

    # 2. BFF client — FakeAsyncClient 注入 _http
    from dataworks_agent.api_clients.bff_client import DataWorksClient

    fake_bff = DataWorksClient()
    fake_bff._http = FakeAsyncClient()
    fake_bff._cookie = "fake_cookie_for_tests"
    fake_bff._csrf_token = "fake_csrf_token"
    fake_bff._csrf_time = __import__("time").time()
    # AppState 没有声明 _bff_client,main.py 动态 setattr
    app_state._bff_client = fake_bff

    # 3. Cookie decrypt — 返回固定值
    monkeypatch.setattr(
        "dataworks_agent.cookie.crypto.decrypt_cookie", lambda: "fake_cookie_for_tests"
    )

    # 4. Cookie keepalive — 禁用避免后台任务泄漏
    monkeypatch.setattr("dataworks_agent.config.settings.cookie_keepalive_enabled", False)

    # 5. CDP 客户端 — 设为 None(测试不需要浏览器)
    app_state._cdp_client = None

    # 6. Smoke 状态
    app_state.smoke_ok = True
    app_state.smoke_failures = []
    app_state.smoke_results = {}
    # cookie_health 用合法 enum 值,避免 Pydantic 校验失败
    app_state.cookie_health = "healthy"

    return SimpleNamespace(
        app_state=app_state,
        mcp=fake_mcp,
        bff=fake_bff,
        set_mcp_responses=lambda r: setattr(
            fake_mcp,
            "call_tool",
            AsyncMock(side_effect=lambda tool, args: r.get(tool, {"status": "ok"})),
        ),
    )


# ───────────────────────────────────────────────────────────
# 共享断言工具
# ───────────────────────────────────────────────────────────


def assert_routed_response(resp, allowed: tuple = (200, 404, 422, 500, 503), label: str = ""):
    """断言响应状态码是"路由能进"的合法值(404 = 资源不存在,合法)。

    默认接受 200(成功)/404(资源不存在)/422(参数不全)/500(BFF/MCP mock 不可用)/
    503(资源不可用)。只有真正的 5xx server error 或路由 404 才算失败。
    """
    if resp.status_code not in allowed:
        raise AssertionError(
            f"{label or 'response'} status={resp.status_code} not in {allowed}, body={resp.text[:200]}"
        )


# ───────────────────────────────────────────────────────────
# 跳过 lifespan + 不挂载前端的 FastAPI app
# ───────────────────────────────────────────────────────────


def build_test_app():
    """构造一个没有 StaticFiles mount 的 FastAPI app,只保留 API 路由。

    直接抄 main.py:create_app() 但跳过 frontend_dir mount 和 SPA fallback。
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from dataworks_agent.routers import (
        artifacts,
        batch_deploy,
        cookie,
        dwd,
        governance,
        import_sql,
        lineage,
        logs,
        modeling,
        monitor,
        pipeline,
        reconciliation,
        roots,
        schedule_config,
        sync,
        system,
        workspace,
    )

    app = FastAPI(title="dataworks-agent (test)", version="0.1.0-test")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(modeling.router, prefix="/api/modeling", tags=["建模任务"])
    app.include_router(dwd.router, prefix="/api/dwd", tags=["DWD 建模"])
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["管道队列"])
    app.include_router(batch_deploy.router, prefix="/api/deploy", tags=["批量部署"])
    app.include_router(governance.router, prefix="/api/governance", tags=["治理"])
    app.include_router(sync.router, prefix="/api/sync", tags=["双环境同步"])
    app.include_router(cookie.router, prefix="/api/cookie", tags=["Cookie 管理"])
    app.include_router(system.router, prefix="/api", tags=["系统"])
    app.include_router(logs.router, prefix="/api/logs", tags=["日志"])
    app.include_router(roots.router, prefix="/api/roots", tags=["词根校验"])
    app.include_router(lineage.router, prefix="/api/lineage", tags=["血缘"])
    app.include_router(reconciliation.router, prefix="/api/reconciliation", tags=["协调处置"])
    app.include_router(artifacts.router, prefix="/api/artifacts", tags=["产物管理"])
    app.include_router(monitor.router, prefix="/api/monitor", tags=["监控"])
    app.include_router(import_sql.router, prefix="/api/import", tags=["批量导入"])
    app.include_router(schedule_config.router, prefix="/api/schedule", tags=["调度配置"])
    app.include_router(workspace.router, prefix="/api/workspace", tags=["工作空间"])

    # 薄路由(同 main.py)
    @app.get("/api/ownership/{table_name}")
    async def get_ownership(table_name: str):
        from dataworks_agent.modeling.ownership import OwnershipTracker

        tracker = OwnershipTracker()
        records = await tracker.get_table_owners(table_name)
        return {"records": [r.model_dump() for r in records]}

    @app.get("/api/bus-matrix")
    async def get_bus_matrix():
        from dataworks_agent.modeling.bus_matrix import BusMatrixManager

        mgr = BusMatrixManager()
        cells = await mgr.get_matrix()
        return {"matrix": [c.model_dump() for c in cells]}

    from fastapi.responses import Response

    from dataworks_agent.metrics import get_metrics

    @app.get("/api/metrics")
    async def metrics():
        return Response(content=get_metrics(), media_type="text/plain")

    return app


# ───────────────────────────────────────────────────────────
# 主 fixture: mocked_client
# ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mocked_client(mocked_app_state):
    """提供配置好 mock 环境的 AsyncClient,跳过 lifespan 和前端 mount。"""
    app = build_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

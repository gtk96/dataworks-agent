"""FastAPI 应用入口 — lifespan 管理、路由挂载、静态文件服务。

服务端口 :8085，serve 前端 dist/ + 提供 REST API + SSE + WebSocket。

启动优化（v12）：
- 所有客户端初始化并行执行（asyncio.gather）
- MCP 连接懒加载（首次调用时才连接，启动不阻塞）
- smoke_check 延迟到首请求（/api/system/health）
- 后台任务（Cookie 保活/刷新/词根同步/备份/监控）全部非阻塞注册
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from dataworks_agent import __version__
from dataworks_agent.config import settings
from dataworks_agent.metrics import get_metrics
from dataworks_agent.state import app_state

logger = logging.getLogger("dataworks_agent")


def _setup_logging() -> None:
    """配置结构化日志：控制台文本 + 文件 JSON 轮转。"""
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "agent.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


_setup_logging()


class NoCacheStaticFiles(StaticFiles):
    """自定义 StaticFiles: index.html 不做浏览器缓存。"""

    async def get_response(self, path: str, scope) -> FileResponse | HTMLResponse:
        response = await super().get_response(path, scope)
        if path.endswith(".html") or path == "":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# ── 并行初始化函数（每个独立 awaitable） ──────────────────────────


async def _init_db() -> None:
    """初始化数据库（同步操作，包在 asyncio 中）。"""
    from dataworks_agent.db.database import init_db

    init_db()
    logger.info("SQLite 数据库就绪: %s", settings.db_path)


async def _init_bff_client() -> None:
    """注册 BFF Cookie 兜底客户端（惰性连接）。"""
    try:
        from dataworks_agent.api_clients.bff_client import DataWorksClient

        app_state._bff_client = DataWorksClient()
        logger.info("DataWorks BFF 客户端已注册（惰性连接）")
    except Exception as e:
        logger.warning("BFF 客户端初始化失败（Cookie 链路长期兜底，缺配置则降级）: %s", e)
        app_state._bff_client = None


async def _init_openapi_clients() -> None:
    """注册 OpenAPI + MaxCompute 客户端（AK/SK）。"""
    try:
        from dataworks_agent.api_clients.maxcompute_client import MaxComputeClient
        from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient
        from dataworks_agent.api_clients.openapi_node_adapter import OpenAPINodeAdapter
        from dataworks_agent.auth import CredentialMissingError, load_credentials

        try:
            creds = load_credentials()
            app_state._openapi_client = DataWorksOpenAPIClient(
                creds=creds,
                region=settings.dataworks_region,
                endpoint=f"dataworks.{settings.dataworks_region}.aliyuncs.com",
                project_id=settings.dataworks_project_id,
            )
            app_state._maxcompute_client = MaxComputeClient(
                creds=creds,
                endpoint=settings.maxcompute_endpoint,
                project=settings.maxcompute_project or settings.dataworks_dev_schema,
            )
            app_state._node_client = OpenAPINodeAdapter(
                app_state._openapi_client,
                project=settings.maxcompute_project or settings.dataworks_dev_schema,
                holo_datasource=settings.holo_node_datasource,
            )
            logger.info("OpenAPI/MaxCompute 客户端就绪 (AK/SK)")
        except CredentialMissingError as e:
            logger.warning("OpenAPI/MaxCompute 客户端未启用（缺 AK/SK）: %s", e)
            app_state._openapi_client = None
            app_state._maxcompute_client = None
            app_state._node_client = None
    except Exception as e:
        logger.warning("OpenAPI/MaxCompute 客户端初始化失败: %s", e)
        app_state._openapi_client = None
        app_state._maxcompute_client = None
        app_state._node_client = None


async def _init_cdp_client() -> None:
    """注册 CDP 客户端（惰性连接）。"""
    try:
        from dataworks_agent.api_clients.cdp_client import CDPClient

        app_state._cdp_client = CDPClient()
        logger.info("CDP 客户端已注册（惰性连接）")
    except Exception as e:
        logger.warning("CDP 客户端不可用: %s", e)
        app_state._cdp_client = None


async def _backfill_node_types() -> int:
    """回填任务 node_type（同步操作）。"""
    from dataworks_agent.services.task_backfill import backfill_node_types

    return backfill_node_types()


async def _check_bind_host() -> None:
    """检查绑定主机安全性。"""
    from dataworks_agent.middleware.client_ip import is_loopback

    bind_host = settings.host or settings.dw_modeling_host
    if (
        not settings.trusted_proxies
        and bind_host not in ("127.0.0.1", "localhost")
        and not is_loopback(bind_host)
    ):
        logger.warning(
            "服务绑定 %s 但 TRUSTED_PROXIES 为空：反代部署下请配置受信代理 IP，"
            "否则多用户 IP 隔离会塌缩为单一 UserContext（v11 §3.3）",
            bind_host,
        )
    elif settings.trusted_proxies:
        logger.info("受信反向代理: %s（ProxyHeadersMiddleware 已启用）", settings.trusted_proxies)


# ── 后台任务注册 ────────────────────────────────────────────────


def _register_background_tasks(app: FastAPI) -> None:
    """注册所有后台任务（全部非阻塞）。"""
    app_state._background_tasks = []

    # Cookie 保活心跳（延迟 15s 启动）
    async def _start_keepalive_later() -> None:
        await asyncio.sleep(15)
        bff = getattr(app_state, "_bff_client", None)
        if bff:
            try:
                from dataworks_agent.cookie.health import cookie_health_monitor

                await cookie_health_monitor.start_keepalive(bff)
            except Exception as e:
                logger.warning("Cookie 保活启动失败: %s", e)

    app_state._background_tasks.append(asyncio.create_task(_start_keepalive_later()))

    # Cookie 后台自助刷新（延迟 30s 启动）
    async def _cookie_refresh_later() -> None:
        await asyncio.sleep(30)
        if settings.auto_login_enabled and settings.cookie_refresh_configured:
            try:
                from dataworks_agent.cookie.background_refresh import (
                    cookie_background_refresh_loop,
                    run_cookie_background_refresh_once,
                )

                stop_event = asyncio.Event()
                app_state._background_tasks.append(
                    asyncio.create_task(cookie_background_refresh_loop(stop_event))
                )
                await run_cookie_background_refresh_once()
            except Exception as exc:
                logger.warning("启动后 Cookie 自助刷新失败: %s", exc)

    app_state._background_tasks.append(asyncio.create_task(_cookie_refresh_later()))

    # 词根同步（延迟 120s 启动）
    async def _word_root_sync_later() -> None:
        await asyncio.sleep(120)
        if settings.word_root_auto_sync_enabled:
            try:
                from dataworks_agent.governance.word_root_sync import (
                    run_word_root_sync_once,
                    word_root_sync_loop,
                )

                stop_event = asyncio.Event()
                app_state._background_tasks.append(
                    asyncio.create_task(word_root_sync_loop(stop_event))
                )
                await run_word_root_sync_once()
            except Exception as exc:
                logger.warning("启动后词根同步失败: %s", exc)

    app_state._background_tasks.append(asyncio.create_task(_word_root_sync_later()))

    # 启动备份调度
    async def _scheduled_backup_task() -> None:
        from dataworks_agent.db.backup import scheduled_backup

        await scheduled_backup()

    app_state._background_tasks.append(asyncio.create_task(_scheduled_backup_task()))

    # 启动任务监控
    async def _monitor_task() -> None:
        from dataworks_agent.task_engine.monitor import task_monitor

        await task_monitor.start()

    app_state._background_tasks.append(asyncio.create_task(_monitor_task()))

    logger.info("后台任务已注册: %d 个", len(app_state._background_tasks))


# ── 应用生命周期 ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 — 启动优化版。"""
    logger.info("dataworks-agent v%s 启动中...", __version__)

    # ── Phase 1: 并行初始化所有客户端（~100ms） ──
    init_tasks = [
        asyncio.create_task(_init_db()),
        asyncio.create_task(_init_bff_client()),
        asyncio.create_task(_init_openapi_clients()),
        asyncio.create_task(_init_cdp_client()),
        asyncio.create_task(_backfill_node_types()),
        asyncio.create_task(_check_bind_host()),
    ]
    results = await asyncio.gather(*init_tasks, return_exceptions=True)
    # 记录异常但不阻塞
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("初始化任务 %d 失败: %s", i, r)

    # ── Phase 2: MCP 懒加载（不阻塞启动） ──
    from dataworks_agent.runtime.lazy_mcp import LazyMCPClient

    lazy_mcp = LazyMCPClient()
    app_state._official_mcp_client = lazy_mcp  # 替换原来的直连客户端
    logger.info("LazyMCP 已注册（首次调用时连接）")

    # ── Phase 3: 注册后台任务（全部非阻塞） ──
    _register_background_tasks(app)
    # 后台预热追加到任务列表，避免被 _register_background_tasks 清空。
    app_state._background_tasks.append(asyncio.create_task(lazy_mcp.warmup(delay=5.0)))

    # ── Phase 4: 启动完成（无需等待 smoke_check） ──
    logger.info("dataworks-agent 启动完成，端口: %s", settings.port)

    yield  # ── 应用运行中 ──

    # ── 关闭阶段 ──
    logger.info("dataworks-agent 正在关闭...")

    # 停止后台任务
    for task in getattr(app_state, "_background_tasks", []):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # 关闭 MCP
    if lazy_mcp:
        await lazy_mcp.close()

    # 关闭 BFF
    if app_state._bff_client:
        await app_state._bff_client.close()

    # 关闭 CDP
    if app_state._cdp_client:
        await app_state._cdp_client.shutdown_chrome()

    logger.info("dataworks-agent 已关闭")


# ── 健康检查端点（首次请求时触发 smoke_check） ──────────────────


async def _get_cached_health() -> dict:
    """获取缓存的健康检查结果，首次调用时触发完整检查。"""
    if not getattr(app_state, "_health_cached", None):
        from dataworks_agent.runtime.smoke_check import startup_smoke_check

        await startup_smoke_check()
        app_state._health_cached = True
    return {
        "status": "ok" if app_state.smoke_ok else "degraded",
        "components": app_state.smoke_results,
        "uptime_seconds": (datetime.now(UTC) - app_state.startup_time).total_seconds(),
    }


# ── FastAPI 应用构建 ────────────────────────────────────────────


def create_app() -> FastAPI:
    """构建 FastAPI 应用实例。"""
    app = FastAPI(
        title="dataworks-agent",
        description="智能数仓建模系统 — DataWorks 全流程自动化",
        version=__version__,
        lifespan=lifespan,
    )

    # ── 中间件 ──
    from dataworks_agent.middleware.idempotency import IdempotencyMiddleware
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware
    from dataworks_agent.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(IPIsolationMiddleware)

    if settings.trusted_proxies:
        from dataworks_agent.middleware.proxy_headers import ProxyHeadersMiddleware

        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8085",
            "http://127.0.0.1:8085",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 注册路由器 ──
    from dataworks_agent.routers import (
        agent,
        artifacts,
        batch_deploy,
        cookie,
        dwd,
        evolution,
        governance,
        import_sql,
        lineage,
        logs,
        modeling,
        monitor,
        pipeline,
        rag,
        reconciliation,
        roots,
        schedule_config,
        sync,
        system,
        workspace,
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
    app.include_router(rag.router, prefix="/api", tags=["RAG 知识检索"])
    app.include_router(evolution.router, tags=["进化模块"])

    if settings.enable_experimental_platform_routes:
        from dataworks_agent.routers import mcp_server, semantic
        from dataworks_agent.runtime import routers as runtime_routers

        app.include_router(semantic.router, prefix="/api/semantic", tags=["Semantic"])
        app.include_router(runtime_routers.router, prefix="/api/runtime", tags=["Runtime"])
        app.include_router(mcp_server.router, prefix="/api/mcp-server", tags=["MCP Server"])

    app.include_router(monitor.router, prefix="/api/monitor", tags=["监控"])
    app.include_router(import_sql.router, prefix="/api/import", tags=["批量导入"])
    app.include_router(schedule_config.router, prefix="/api/schedule", tags=["调度配置"])
    app.include_router(workspace.router, prefix="/api/workspace", tags=["工作空间"])
    app.include_router(agent.router, prefix="/agent", tags=["agent"])

    # SSE streaming for real-time chat
    from dataworks_agent.routers import agent_sse

    app.include_router(agent_sse.router, prefix="/agent", tags=["agent-sse"])

    # ── 薄路由 ──
    @app.get("/api/bus-matrix")
    async def get_bus_matrix():
        from dataworks_agent.routers.governance import get_bus_matrix as _get_bus_matrix

        return await _get_bus_matrix()

    @app.get("/api/ownership/{table_name}")
    async def get_ownership(
        table_name: str,
        limit: int = 50,
        offset: int = 0,
    ):
        from dataworks_agent.modeling.ownership import OwnershipTracker

        tracker = OwnershipTracker()
        if table_name == "all":
            records = await tracker.get_all_owners(limit=limit, offset=offset)
        else:
            records = await tracker.get_table_owners(table_name, limit=limit, offset=offset)
        return {"records": [r.model_dump() for r in records]}

    # Prometheus 指标
    @app.get("/api/metrics")
    async def metrics():
        from fastapi.responses import Response

        return Response(content=get_metrics(), media_type="text/plain")

    # 健康检查（首次触发 smoke_check）
    @app.get("/api/system/health")
    async def system_health():
        """系统健康检查 — 首次调用时触发完整检查，后续返回缓存结果。"""
        return await _get_cached_health()

    # ── 前端静态文件 ──
    frontend_dir = Path(settings.frontend_dir)
    if frontend_dir.exists():
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        app.mount(
            "/",
            StaticFiles(directory=str(frontend_dir), html=True, check_dir=False),
            name="frontend",
        )
        logger.info("前端静态文件: %s", frontend_dir)

    @app.middleware("http")
    async def spa_fallback_middleware(request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404 and not request.url.path.startswith("/api/"):
            index_path = frontend_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path, headers={"Cache-Control": "no-cache"})
        return response

    return app


app = create_app()


def run():
    """uvicorn 入口。"""
    import uvicorn

    uvicorn.run(
        "dataworks_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()

"""FastAPI 应用入口 — lifespan 管理、路由挂载、静态文件服务。

服务端口 :8085，serve 前端 dist/ + 提供 REST API + SSE + WebSocket。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # ── 启动阶段 ──
    logger.info("dataworks-agent v%s 启动中...", __version__)

    # 1. 初始化数据库
    from dataworks_agent.db.database import init_db

    init_db()
    logger.info("SQLite 数据库就绪: %s", settings.db_path)

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

    from dataworks_agent.services.task_backfill import backfill_node_types

    backfilled = backfill_node_types()
    if backfilled:
        logger.info("已回填 %d 条任务的 node_type", backfilled)

    # 2. CDP 客户端（惰性连接；Cookie 链路长期兜底，缺配置则优雅降级）
    try:
        from dataworks_agent.api_clients.cdp_client import CDPClient

        app_state._cdp_client = CDPClient()
        logger.info("CDP 客户端已注册（惰性连接）")
    except Exception as e:
        logger.warning("CDP 客户端不可用（Cookie 链路长期兜底，缺配置则降级）: %s", e)
        app_state._cdp_client = None

    # 3. 初始化 MCP（认证走 mcp.json 的 Bearer token，与 Cookie 无关）+ BFF（Cookie 链路，缺配置则降级）
    try:
        from dataworks_agent.mcp.pool import MCPClientPool

        mcp_pool = MCPClientPool()
        await mcp_pool.connect()
        app_state.mcp_pool = mcp_pool
        logger.info("MCP 连接池就绪")
    except Exception as e:
        logger.warning("MCP 连接池初始化失败（服务降级运行）: %s", e)
        app_state.mcp_pool = None

    try:
        from dataworks_agent.api_clients.bff_client import DataWorksClient

        app_state._bff_client = DataWorksClient()
        logger.info("DataWorks 客户端就绪")
    except Exception as e:
        logger.warning("DataWorks 客户端初始化失败（Cookie 链路长期兜底，缺配置则降级）: %s", e)
        app_state._bff_client = None

    # 3b. OpenAPI 执行底座（AK/SK；与 BFF 长期并存，缺凭证则降级）
    try:
        from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient
        from dataworks_agent.auth import CredentialMissingError, load_credentials

        try:
            creds = load_credentials()
            app_state._openapi_client = DataWorksOpenAPIClient(
                creds=creds,
                region=settings.dataworks_region,
                endpoint=f"dataworks.{settings.dataworks_region}.aliyuncs.com",
                project_id=settings.dataworks_project_id,
            )
            logger.info("DataWorks OpenAPI 客户端就绪 (AK/SK)")

            from dataworks_agent.api_clients.maxcompute_client import MaxComputeClient

            app_state._maxcompute_client = MaxComputeClient(
                creds=creds,
                endpoint=settings.maxcompute_endpoint,
                project=settings.maxcompute_project,
            )
            logger.info("MaxCompute 客户端就绪 (AK/SK)")

            # 节点操作 AK/SK 适配器（drop-in 替换 bff 的节点 5 方法；Task 8b）。
            # 仅构造备用，生产建节点/发布须经 Publish_Gate 人工授权后再切调用点。
            from dataworks_agent.api_clients.openapi_node_adapter import OpenAPINodeAdapter

            app_state._node_client = OpenAPINodeAdapter(
                app_state._openapi_client,
                project=settings.maxcompute_project,
                holo_datasource=settings.holo_node_datasource,
            )
            logger.info("OpenAPI 节点适配器就绪 (AK/SK, 待接线)")
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

    # 4. Cookie 保活 (轻量 BFF 心跳，不刷新浏览器)
    from dataworks_agent.cookie.health import cookie_health_monitor

    await cookie_health_monitor.start_keepalive(app_state._bff_client)

    # 4b. Cookie 后台自助刷新（CDP 定时校验 + 失效重提取）
    from dataworks_agent.cookie.background_refresh import (
        cookie_background_refresh_loop,
        run_cookie_background_refresh_once,
    )

    _cookie_refresh_stop = asyncio.Event()
    _cookie_refresh_task = asyncio.create_task(cookie_background_refresh_loop(_cookie_refresh_stop))
    app_state._background_tasks = getattr(app_state, "_background_tasks", [])
    app_state._background_tasks.append(_cookie_refresh_task)

    async def _bootstrap_cookie_refresh() -> None:
        await asyncio.sleep(5)
        if settings.auto_login_enabled and settings.cookie_refresh_configured:
            try:
                await run_cookie_background_refresh_once()
            except Exception as exc:
                logger.warning("启动后 Cookie 自助刷新失败: %s", exc)

    _bootstrap_task = asyncio.create_task(_bootstrap_cookie_refresh())
    app_state._background_tasks.append(_bootstrap_task)

    # 4c. 词根表后台自动同步（默认每 2 小时拉生产 dim_pub_column_dictionary_static）
    from dataworks_agent.governance.word_root_sync import (
        run_word_root_sync_once,
        word_root_sync_loop,
    )

    _word_root_sync_stop = asyncio.Event()
    _word_root_sync_task = asyncio.create_task(word_root_sync_loop(_word_root_sync_stop))
    app_state._background_tasks.append(_word_root_sync_task)

    async def _bootstrap_word_root_sync() -> None:
        await asyncio.sleep(10)
        if settings.word_root_auto_sync_enabled:
            try:
                await run_word_root_sync_once()
            except Exception as exc:
                logger.warning("启动后词根同步失败: %s", exc)

    _word_root_bootstrap_task = asyncio.create_task(_bootstrap_word_root_sync())
    app_state._background_tasks.append(_word_root_bootstrap_task)

    # 4. 冒烟检查
    from dataworks_agent.bootstrap import startup_smoke_check

    await startup_smoke_check()

    # 5. 启动备份调度
    from dataworks_agent.db.backup import scheduled_backup

    backup_task = asyncio.create_task(scheduled_backup())
    # 给 shutdown 时清理用，避免 dangling task warning
    app_state._background_tasks = getattr(app_state, "_background_tasks", [])
    app_state._background_tasks.append(backup_task)

    # 6. 启动任务监控
    from dataworks_agent.task_engine.monitor import task_monitor

    await task_monitor.start()

    logger.info("dataworks-agent 启动完成，端口: %s", settings.port)

    yield  # ── 应用运行中 ──

    # ── 关闭阶段 ──
    logger.info("dataworks-agent 正在关闭...")
    await task_monitor.stop()
    await cookie_health_monitor.stop_keepalive()
    _cookie_refresh_stop.set()
    _cookie_refresh_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _cookie_refresh_task
    _word_root_sync_stop.set()
    _word_root_sync_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _word_root_sync_task
    if app_state.mcp_pool:
        await app_state.mcp_pool.disconnect()
    if app_state._bff_client:
        await app_state._bff_client.close()
    if app_state._cdp_client:
        await app_state._cdp_client.shutdown_chrome()
    logger.info("dataworks-agent 已关闭")


def create_app() -> FastAPI:
    """构建 FastAPI 应用实例。"""
    app = FastAPI(
        title="dataworks-agent",
        description="智能数仓建模系统 — DataWorks 全流程自动化",
        version=__version__,
        lifespan=lifespan,
    )

    # ── 中间件(顺序: 后注册先执行; 限流最内, CORS 最外) ──
    from dataworks_agent.middleware.idempotency import IdempotencyMiddleware
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware
    from dataworks_agent.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # IP 隔离要在 Idempotency 之前,让 Idempotency 拿到正确的 request.state.client_ip
    app.add_middleware(IPIsolationMiddleware)
    # v11 §3.3：仅当配置了 trusted_proxies 才信任 X-Forwarded-For（Starlette 官方实现）
    if settings.trusted_proxies:
        from dataworks_agent.middleware.proxy_headers import ProxyHeadersMiddleware

        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)

    # CORS（仅允许本地开发）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
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

    # L0 基础路由
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

    # Slim default: keep Agent-first core exposed; L1-L5 skeleton routes are opt-in.
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

    # ── 前端静态文件 ──
    frontend_dir = Path(settings.frontend_dir)
    if frontend_dir.exists():
        # 先挂载 assets 子目录
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        # 挂载 favicon 等根文件
        app.mount(
            "/",
            StaticFiles(directory=str(frontend_dir), html=True, check_dir=False),
            name="frontend",
        )
        logger.info("前端静态文件: %s", frontend_dir)

    # SPA fallback 中间件: 非 API 路径 404 时返回 index.html
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
    """uvicorn 入口 — `python -m dataworks_agent.main` 或 `dw-agent` 命令。"""
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

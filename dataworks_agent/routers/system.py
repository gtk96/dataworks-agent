"""系统 API — 健康检查 + 配置管理。"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from dataworks_agent import __version__
from dataworks_agent.config import settings
from dataworks_agent.schemas import HealthChecks, HealthResponse
from dataworks_agent.state import app_state

router = APIRouter()
_start_time = time.time()


@router.get("/health")
async def health():
    """健康检查 — BFF + MCP + Cookie + DB（CDP 非必须）。"""
    uptime = int(time.time() - _start_time)

    # 使用启动检查结果（避免每次 health check 都重连 CDP）
    sr = app_state.smoke_results
    official_mcp = getattr(app_state, "_official_mcp_client", None)
    official_connected = bool(
        official_mcp is not None and getattr(official_mcp.status, "connected", False)
    )
    mcp_ok = "ok" if official_connected or sr.get("official_mcp", {}).get("ok") else "degraded"
    bff_ok = "ok" if sr.get("bff", {}).get("ok") else "degraded"
    cdp_ok = "ok" if sr.get("cdp", {}).get("ok") else "degraded"
    cookie_ok = "ok" if sr.get("cookie", {}).get("ok") else "degraded"

    # cookie_expires_in: 从 app_state.cookie_health 推断合理值
    ch = app_state.cookie_health
    _expires_in = {
        "healthy": 86400,
        "warning": 3600,
        "critical": 300,
        "expired": 0,
        "degraded": 0,
    }.get(ch, 0)

    checks = HealthChecks(
        bff_api=bff_ok,
        cdp=cdp_ok,
        mcp=mcp_ok,
        cookie=cookie_ok,
        cookie_expires_in=_expires_in,
        cookie_health=app_state.cookie_health,
        db="ok" if sr.get("db", {}).get("ok") else "degraded",
    )

    # CDP 不是必须项（AK/SK 架构下预期不可用）
    ok_count = sum(1 for v in [mcp_ok, bff_ok, cookie_ok] if v == "ok")
    db_ok = checks.db == "ok"
    if ok_count >= 2 and db_ok:
        status = "ok"
    elif ok_count >= 1:
        status = "degraded"
    else:
        status = "down"

    return HealthResponse(
        status=status,
        version=__version__,
        uptime_seconds=uptime,
        checks=checks,
    )


@router.get("/settings")
async def get_settings():
    """获取当前配置（脱敏）。"""
    import os

    return {
        "project_id": settings.dataworks_project_id,
        "region": settings.dataworks_region,
        "dev_schema": settings.dataworks_dev_schema,
        "prod_schema": settings.dataworks_prod_schema,
        "port": settings.port,
        "cookie_keepalive": settings.cookie_keepalive_enabled,
        "auto_login_enabled": settings.auto_login_enabled,
        "cookie_refresh_poll_seconds": settings.cookie_refresh_poll_seconds,
        "cookie_bg_poll": app_state.cookie_bg_poll,
        "aksk_configured": bool(os.environ.get("ALIYUN_ACCESS_KEY_ID")),
        "smoke_ok": app_state.smoke_ok,
        "smoke_results": app_state.smoke_results,
    }


@router.patch("/settings")
async def update_settings():
    """更新配置（当前版本不支持，留 Phase 2）。"""
    raise HTTPException(status_code=501, detail="Settings API (Phase 2: .env 热更新)")

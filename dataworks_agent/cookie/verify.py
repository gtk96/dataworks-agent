"""Cookie 有效性校验 — BFF 与 CDP 两通道独立验证。"""

from __future__ import annotations

import asyncio

from dataworks_agent.cookie.crypto import decrypt_cookie


async def verify_cookie_via_bff(bff_client) -> dict:
    """通过 BFF 轻量接口验证 Cookie 有效性。"""
    try:
        await asyncio.wait_for(bff_client._refresh_csrf(), timeout=10)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "expired", "error": str(e)[:80]}


async def verify_cookie_via_cdp(cdp_client) -> dict:
    """通过 CDP 验证 Chrome 连接状态。"""
    try:
        page = await asyncio.wait_for(cdp_client.get_ide_page(), timeout=10)
        return {"status": "ok" if page else "degraded"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


async def full_cookie_health_check(bff_client, cdp_client) -> dict:
    """Cookie 健康检查 — BFF 负责鉴权，CDP 负责自动续期可用性。"""
    results = {
        "bff": await verify_cookie_via_bff(bff_client) if bff_client else {"status": "unknown"},
        "cdp": await verify_cookie_via_cdp(cdp_client) if cdp_client else {"status": "unknown"},
    }
    bff_status = results["bff"]["status"]
    cdp_status = results["cdp"]["status"]
    if bff_status == "ok" and cdp_status in {"ok", "unknown"}:
        overall = "healthy"
    elif bff_status == "ok":
        overall = "degraded"
    elif bff_status == "unknown":
        overall = "unknown"
    else:
        overall = "expired"
    return {"overall": overall, "channels": results}


def get_cookie_header() -> str:
    """获取用于 HTTP 请求的 Cookie 头。"""
    return decrypt_cookie() or ""

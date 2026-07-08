"""Cookie 有效性校验 — 三通道 (BFF / MCP / CDP) 独立验证。"""

from __future__ import annotations

import asyncio

from dataworks_agent.cookie.crypto import decrypt_cookie


async def verify_cookie_via_mcp(mcp_pool) -> dict:
    """通过 MCP 验证 Cookie 有效性。"""
    try:
        result = await asyncio.wait_for(
            mcp_pool.call_tool("get_current_user", {}),
            timeout=10,
        )
        return {"status": "ok", "user": result.get("username", "unknown")}
    except Exception as e:
        return {"status": "expired", "error": str(e)}


async def verify_cookie_via_bff(bff_client) -> dict:
    """通过 BFF 轻量接口验证 Cookie 有效性（/csrf 无需项目权限）。"""
    try:
        await asyncio.wait_for(
            bff_client._refresh_csrf(),
            timeout=10,
        )
        return {"status": "ok"}
    except Exception as e:
        return {"status": "expired", "error": str(e)[:80]}


async def verify_cookie_via_cdp(cdp_client) -> dict:
    """通过 CDP 验证 Chrome 连接状态。"""
    try:
        page = await asyncio.wait_for(
            cdp_client.get_ide_page(),
            timeout=10,
        )
        return {"status": "ok" if page else "degraded"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


async def full_cookie_health_check(mcp_pool, bff_client, cdp_client) -> dict:
    """三通道 Cookie 健康检查 — 覆盖 BFF + MCP + CDP。"""
    results = {}

    # MCP 通道
    if mcp_pool:
        results["mcp"] = await verify_cookie_via_mcp(mcp_pool)
    else:
        results["mcp"] = {"status": "unknown"}

    # BFF 通道
    if bff_client:
        results["bff"] = await verify_cookie_via_bff(bff_client)
    else:
        results["bff"] = {"status": "unknown"}

    # CDP 通道
    if cdp_client:
        results["cdp"] = await verify_cookie_via_cdp(cdp_client)
    else:
        results["cdp"] = {"status": "unknown"}

    # 综合判定
    statuses = [v["status"] for v in results.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif all(s != "ok" for s in statuses):
        overall = "expired"
    else:
        overall = "degraded"

    return {"overall": overall, "channels": results}


def get_cookie_header() -> str:
    """获取用于 HTTP 请求的 Cookie 头。"""
    cookie = decrypt_cookie()
    if not cookie:
        return ""
    return cookie

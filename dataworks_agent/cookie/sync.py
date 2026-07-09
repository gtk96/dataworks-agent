"""Cookie 写入后的 BFF / MCP 同步。"""

from __future__ import annotations

import logging

from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


def invalidate_bff_session(bff) -> None:
    """清空 BFF 内存 Cookie 与相关缓存，强制下次请求重读 cookie.dat。"""
    if bff is None:
        return
    bff._cookie = ""
    bff._csrf_token = ""
    bff._csrf_time = 0
    bff._datasource_cache = None
    bff._datasource_cache_time = 0
    bff._node_list_cache = None
    bff._node_list_cache_time = 0


async def sync_cookie_to_mcp(mcp_pool, cookie: str) -> tuple[bool, str]:
    """将 Cookie 同步到 MCP（HTTP 头 + update_cookie 工具）。"""
    if not mcp_pool or not cookie:
        return True, ""

    mcp_pool.set_cookie_header(cookie)

    try:
        result = await mcp_pool.call_tool("update_cookie", {"cookie": cookie})
        if isinstance(result, dict):
            if result.get("success") is False:
                msg = str(result.get("message") or result.get("error") or "update_cookie 失败")
                return False, msg[:400]
            if result.get("error"):
                return False, str(result["error"])[:400]
        return True, ""
    except RuntimeError as exc:
        err = str(exc)
        if "Session not found" in err or "404" in err:
            logger.info("MCP 会话失效，尝试重连后同步 Cookie")
            try:
                await mcp_pool.reconnect()
                await mcp_pool.call_tool("update_cookie", {"cookie": cookie})
                return True, ""
            except Exception as retry_exc:
                logger.warning("MCP 重连后 update_cookie 仍失败: %s", retry_exc)
                return False, str(retry_exc)[:400]
        logger.warning("update_cookie 调用失败（仍保留 HTTP Cookie 头）: %s", exc)
        return True, ""
    except Exception as exc:
        logger.warning("update_cookie 调用失败（仍保留 HTTP Cookie 头）: %s", exc)
        return True, ""


async def apply_cookie_update(cookie: str) -> None:
    """保存 Cookie 后：刷新 BFF 内存态并同步 MCP。"""
    bff = getattr(app_state, "_bff_client", None)
    invalidate_bff_session(bff)
    ok, err = await sync_cookie_to_mcp(app_state.mcp_pool, cookie)
    if not ok:
        logger.warning("MCP Cookie 同步未完全成功: %s", err)

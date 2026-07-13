"""Cookie 写入后的 BFF 会话刷新。"""

from __future__ import annotations

from dataworks_agent.state import app_state


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


async def apply_cookie_update(cookie: str) -> None:
    """保存 Cookie 后刷新 BFF 内存态；Cookie 不再同步到外部 data-mcp。"""
    del cookie
    invalidate_bff_session(getattr(app_state, "_bff_client", None))

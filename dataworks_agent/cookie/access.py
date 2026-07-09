"""Cookie 有效性校验 — BFF 业务接口 + MCP。"""

from __future__ import annotations

import logging

from dataworks_agent.cookie.crypto import decrypt_cookie
from dataworks_agent.cookie.sync import invalidate_bff_session, sync_cookie_to_mcp

logger = logging.getLogger(__name__)


async def verify_cookie_access(
    cookie: str | None = None,
    *,
    bff=None,
    mcp_pool=None,
) -> tuple[bool, str, str]:
    """校验 Cookie 能否访问 DataWorks（BFF + MCP）。

    Returns:
        (ok, error_message, username)
    """
    cookie = (cookie or decrypt_cookie() or "").strip()
    if not cookie:
        return False, "未配置 Cookie", ""

    username = ""
    mcp_err = ""
    bff_err = ""
    bff_ok = True
    mcp_ok = True

    if mcp_pool:
        try:
            ok, sync_err = await sync_cookie_to_mcp(mcp_pool, cookie)
            if not ok:
                mcp_ok = False
                mcp_err = sync_err
            else:
                user = await mcp_pool.call_tool("get_current_user", {})
                if isinstance(user, dict):
                    if user.get("error"):
                        mcp_ok = False
                        mcp_err = str(user["error"])[:400]
                    else:
                        username = str(user.get("username") or user.get("display_name") or "")
                elif user:
                    username = str(user)[:80]
        except Exception as exc:
            mcp_ok = False
            mcp_err = f"MCP 校验失败: {str(exc)[:200]}"

    if bff:
        invalidate_bff_session(bff)
        try:
            resp = await bff._get(
                "v1/ListDatasources2",
                {
                    "projectId": bff.project_id,
                    "tenantId": bff.tenant_id,
                    "productCode": "di",
                    "pageSize": 10,
                    "onlyShowDiSupport": "false",
                },
            )
            code = resp.get("code")
            if code not in (200, "200"):
                bff_ok = False
                bff_err = str(resp.get("message") or resp.get("msg") or f"BFF code={code}")[:400]
        except Exception as exc:
            bff_ok = False
            bff_err = f"BFF 校验失败: {str(exc)[:200]}"

    # BFF 是数据集成主链路；MCP Bearer 失效时不阻断 DI
    if bff_ok:
        return True, mcp_err if not mcp_ok else "", username
    if mcp_ok:
        return True, "", username
    return False, bff_err or mcp_err or "Cookie 无效", username

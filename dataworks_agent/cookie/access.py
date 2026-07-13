"""Cookie 有效性校验 — 通过 DataWorks BFF 业务接口验证。"""

from __future__ import annotations

from dataworks_agent.cookie.crypto import decrypt_cookie
from dataworks_agent.cookie.sync import invalidate_bff_session


async def verify_cookie_access(cookie: str | None = None, *, bff=None) -> tuple[bool, str, str]:
    """校验 Cookie 能否访问 DataWorks BFF，返回 ``(ok, error, username)``。"""
    cookie = (cookie or decrypt_cookie() or "").strip()
    if not cookie:
        return False, "未配置 Cookie", ""
    if bff is None:
        return False, "BFF 客户端未初始化", ""
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
            error = str(resp.get("message") or resp.get("msg") or f"BFF code={code}")[:400]
            return False, error, ""
        return True, "", ""
    except Exception as exc:
        return False, f"BFF 校验失败: {str(exc)[:200]}", ""

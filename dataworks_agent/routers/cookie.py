"""Cookie 管理 API — 存储、验证、自动提取。"""

from __future__ import annotations

import asyncio
import hmac

from fastapi import APIRouter, HTTPException, Request

from dataworks_agent.cookie.crypto import decrypt_cookie, has_cookie, save_cookie
from dataworks_agent.cookie.sync import apply_cookie_update
from dataworks_agent.cookie.verify import full_cookie_health_check
from dataworks_agent.middleware.client_ip import is_loopback, peer_ip
from dataworks_agent.schemas import CookieSaveRequest, CookieStatusResponse

router = APIRouter()


def _require_local(request: Request) -> None:
    """仅允许本机 TCP 直连访问敏感端点（v9 §2.2：不信任 X-Forwarded-For）。"""
    if not is_loopback(peer_ip(request)):
        raise HTTPException(status_code=403, detail="仅限本机访问")


def _require_admin_token(request: Request, token: str) -> None:
    """校验 Admin Token（HMAC over COOKIE_ENCRYPTION_KEY），用于程序化访问。"""
    from dataworks_agent.config import settings

    expected = hmac.new(
        settings.cookie_encryption_key.encode(), b"admin-access", "sha256"
    ).hexdigest()[:16]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="无效的 Admin Token")


def _audit_cookie(action: str, request: Request, **kwargs) -> None:
    from dataworks_agent.services.audit import audit_log

    audit_log(action, ip=peer_ip(request), **kwargs)


@router.post("")
async def save_cookie_endpoint(body: CookieSaveRequest, request: Request):
    """保存 DataWorks Cookie（加密存储）。"""
    if not body.cookie_string or len(body.cookie_string) < 20:
        raise HTTPException(status_code=400, detail="Cookie 字符串无效")
    save_cookie(body.cookie_string)
    await apply_cookie_update(body.cookie_string)
    _audit_cookie("cookie_save", request, length=len(body.cookie_string))
    return {"message": "Cookie 已加密保存", "length": len(body.cookie_string)}


@router.get("/status")
async def cookie_status(request: Request):
    """获取 Cookie 状态。"""
    if not has_cookie():
        return CookieStatusResponse(valid=False, expires_in=0, health="expired")

    from dataworks_agent.state import app_state

    return CookieStatusResponse(
        valid=app_state.cookie_health in ("healthy", "warning"),
        expires_in=0,
        health=app_state.cookie_health,
    )


@router.get("/verify")
async def verify_cookie(request: Request):
    """验证 Cookie 有效性（BFF + CDP）。"""
    from dataworks_agent.state import app_state

    bff = getattr(app_state, "_bff_client", None)
    cdp = getattr(app_state, "_cdp_client", None)
    result = await full_cookie_health_check(bff, cdp)
    return result


@router.get("/full")
async def get_cookie_full(request: Request, token: str = ""):
    """获取完整 Cookie 明文（需要 IP 白名单 + Admin Token，供程序化调用）。"""
    _require_local(request)
    _require_admin_token(request, token)

    cookie = decrypt_cookie()
    if not cookie:
        raise HTTPException(status_code=404, detail="Cookie 未配置")
    _audit_cookie("cookie_full", request, length=len(cookie))
    return {"cookie": cookie}


@router.get("/copy")
async def copy_cookie(request: Request):
    """复制 Cookie 明文（仅本机 TCP 直连，供设置页"复制 Cookie"按钮使用）。"""
    _require_local(request)

    cookie = decrypt_cookie()
    if not cookie:
        raise HTTPException(status_code=404, detail="Cookie 未配置")
    _audit_cookie("cookie_copy", request, length=len(cookie))
    return {"cookie": cookie}


@router.get("/bg-poll")
async def cookie_bg_poll_status():
    """后台 Cookie 轮询状态。"""
    from dataworks_agent.config import settings
    from dataworks_agent.state import app_state

    poll = dict(app_state.cookie_bg_poll)
    poll["auto_refresh_enabled"] = bool(
        settings.auto_login_enabled and settings.cookie_refresh_configured
    )
    poll["poll_seconds"] = settings.cookie_refresh_poll_seconds
    return poll


@router.post("/auto-fetch")
async def auto_fetch_cookie(request: Request):
    """通过 CDP Network.getCookies 提取全部 Cookie（含 httpOnly）。"""
    from dataworks_agent.cookie.background_refresh import cdp_extract_and_apply

    try:
        result = await cdp_extract_and_apply()
        if result["status"] == "success":
            detail = result.get("detail", "")
            length = int(detail.split()[0]) if detail.split() and detail.split()[0].isdigit() else 0
            _audit_cookie("cookie_auto_fetch", request, length=length)
            return {"message": "Cookie 已自动提取", "length": length or detail}
        if result["status"] == "skipped":
            raise HTTPException(status_code=429, detail=result.get("detail", "退避中"))
        detail = result.get("detail", "未能提取到有效 Cookie")
        if detail == "CDP 客户端不可用":
            raise HTTPException(status_code=503, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自动提取失败: {e}") from e


@router.post("/wait-login")
async def wait_for_login(request: Request):
    """打开 DataWorks 登录页并等待用户扫码登录（最长 2 分钟）。"""
    from dataworks_agent.state import app_state

    cdp = getattr(app_state, "_cdp_client", None)
    if not cdp:
        raise HTTPException(status_code=503, detail="CDP 客户端不可用")

    try:
        await cdp.ensure_chrome(auto_launch=True)
        logged_in = await cdp.wait_for_login(timeout=120)
        if logged_in:
            from dataworks_agent.cookie.background_refresh import cdp_extract_and_apply

            result = await cdp_extract_and_apply()
            if result["status"] == "success":
                _audit_cookie("cookie_wait_login", request, detail=result.get("detail"))
                return {
                    "status": "ok",
                    "message": f"登录成功，已提取 Cookie ({result.get('detail', '')})",
                }
            _audit_cookie("cookie_wait_login", request, length=0, detail="extract_failed")
            return {"status": "ok", "message": "登录成功但 Cookie 提取失败"}
        raise HTTPException(
            status_code=408, detail="登录等待超时，请在浏览器中手动扫码后点击'自动提取'"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登录流程异常: {e}") from e


@router.get("/scan-uuids")
async def scan_uuids(request: Request):
    """通过 CDP 抓取 IDE 页面所有网络请求（15 秒窗口，仅本机 TCP 直连）。"""
    _require_local(request)
    _audit_cookie("cookie_scan_uuids", request)

    from dataworks_agent.state import app_state

    cdp = getattr(app_state, "_cdp_client", None)
    if not cdp:
        raise HTTPException(status_code=503, detail="CDP 不可用")

    try:
        await cdp._ensure_connected()
    except Exception as e:
        return {"error": f"CDP 连接失败: {e}"}

    page = cdp._page

    captured: list[str] = []

    def on_request(req):
        url = req.url
        method = req.method
        if "data.aliyun.com" in url or "dataworks" in url:
            post_data = req.post_data or ""
            captured.append(f"{method} {url.split('?')[0].split('/')[-1]} {post_data[:120]}")

    page.on("request", on_request)

    try:
        await asyncio.sleep(15)
    except Exception as e:
        captured.append(f"error: {e}")
    finally:
        page.remove_listener("request", on_request)

    return {"captured": captured[-100:], "count": len(captured)}


@router.post("/launch-browser")
async def launch_browser(request: Request):
    """启动 Chrome 浏览器并导航到 DataWorks IDE。"""
    from dataworks_agent.state import app_state

    cdp = getattr(app_state, "_cdp_client", None)
    if cdp:
        try:
            await cdp.navigate_to_ide()
            _audit_cookie("cookie_launch_browser", request)
            return {"message": "已导航到 DataWorks IDE"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"导航失败: {e}") from e
    raise HTTPException(status_code=503, detail="CDP 客户端不可用")

"""Cookie 后台定时刷新 — 失效时从 CDP 调试浏览器自助提取。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from dataworks_agent.api_clients.cdp_client import _is_cdp_alive
from dataworks_agent.config import settings
from dataworks_agent.cookie.access import verify_cookie_access
from dataworks_agent.cookie.crypto import decrypt_cookie, save_cookie
from dataworks_agent.cookie.extract_state import extract_state
from dataworks_agent.cookie.sync import apply_cookie_update
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


def _now_str(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts or time.time()))


def touch_cookie_poll(*, action: str, detail: str = "") -> None:
    """更新后台轮询状态（供 status API 展示）。"""
    now = time.time()
    poll = app_state.cookie_bg_poll
    poll["last_poll_ts"] = int(now)
    poll["last_poll_str"] = _now_str(now)
    poll["last_action"] = action
    poll["last_detail"] = detail
    if settings.auto_login_enabled and settings.cookie_refresh_configured:
        next_ts = now + settings.cookie_refresh_poll_seconds
        poll["next_poll_ts"] = int(next_ts)
        poll["next_poll_str"] = _now_str(next_ts)
    else:
        poll["next_poll_ts"] = 0
        poll["next_poll_str"] = ""


async def cdp_extract_and_apply() -> dict:
    """从 CDP 调试浏览器提取 Cookie 并写入 + 同步。"""
    if extract_state.should_skip_due_to_backoff():
        return {
            "status": "skipped",
            "detail": f"退避中，{extract_state.backoff_seconds}s 后重试",
        }

    cdp = getattr(app_state, "_cdp_client", None)
    if not cdp:
        return {"status": "failed", "detail": "CDP 客户端不可用"}

    if not await _is_cdp_alive(settings.cdp_url):
        return {"status": "failed", "detail": "调试浏览器未运行（:9222）"}

    async with extract_state._lock:
        if extract_state.is_running:
            return {"status": "skipped", "detail": "busy"}
        extract_state.record_start()
        try:
            logged_in = await cdp.check_logged_in()
            if not logged_in:
                extract_state.record_failure()
                return {
                    "status": "failed",
                    "detail": "调试浏览器未登录 DataWorks，请先完成登录",
                }

            cookie_str = await cdp.extract_cookies_via_cdp()
            if not cookie_str or len(cookie_str) < 20:
                extract_state.record_failure()
                return {"status": "failed", "detail": "提取到的 Cookie 为空"}

            save_cookie(cookie_str)
            await apply_cookie_update(cookie_str)
            extract_state.record_success()
            return {"status": "success", "detail": f"{len(cookie_str)} 字符"}
        except Exception as exc:
            extract_state.record_failure()
            logger.warning("CDP Cookie 提取失败: %s", exc)
            return {"status": "failed", "detail": str(exc)[:200]}


async def run_cookie_background_refresh_once(*, force: bool = False) -> dict:
    """单次后台刷新：Cookie 有效则跳过；失效则 CDP 提取。"""
    if not settings.cookie_refresh_configured:
        touch_cookie_poll(action="skipped", detail="未配置 CDP_URL")
        return {"status": "skipped", "detail": "未配置 CDP"}

    if extract_state.is_running:
        touch_cookie_poll(action="skipped", detail="已有提取任务进行中")
        return {"status": "skipped", "detail": "busy"}

    bff = getattr(app_state, "_bff_client", None)
    mcp = app_state.mcp_pool
    cookie = ""
    try:
        cookie = decrypt_cookie()
    except Exception as exc:
        logger.warning("读取 Cookie 失败，将尝试 CDP 提取: %s", exc)

    err = ""
    if cookie and not force:
        try:
            ok, err, username = await verify_cookie_access(cookie, bff=bff, mcp_pool=mcp)
            if ok:
                if err:
                    app_state.cookie_health = "degraded"
                elif mcp:
                    from dataworks_agent.cookie.health import cookie_health_monitor

                    await cookie_health_monitor.check(mcp)
                else:
                    app_state.cookie_health = "healthy"
                touch_cookie_poll(
                    action="valid",
                    detail=f"Cookie 仍有效（{username or '—'}）",
                )
                return {"status": "valid", "detail": username or "ok"}
        except Exception as exc:
            logger.debug("Cookie 校验异常，尝试 CDP 提取: %s", exc)
            err = str(exc)
        if not err:
            err = "校验未通过"
        logger.info("Cookie 失效，尝试 CDP 自助提取: %s", err[:120])
    else:
        err = "未配置 Cookie" if not cookie else "强制刷新"

    touch_cookie_poll(action="extracting", detail=err[:200])

    result = await cdp_extract_and_apply()

    if result["status"] == "success":
        try:
            ok, verify_err, username = await verify_cookie_access(bff=bff, mcp_pool=mcp)
            if ok:
                if verify_err:
                    app_state.cookie_health = "degraded"
                elif mcp:
                    from dataworks_agent.cookie.health import cookie_health_monitor

                    await cookie_health_monitor.check(mcp)
                else:
                    app_state.cookie_health = "healthy"
                touch_cookie_poll(
                    action="refreshed",
                    detail=f"已同步（{username or '—'}）"
                    + (f"；MCP: {verify_err[:80]}" if verify_err else ""),
                )
                return {"status": "refreshed", "detail": username or "ok"}
            touch_cookie_poll(action="extracted_unverified", detail=verify_err or "校验未通过")
            return {"status": "extracted_unverified", "detail": verify_err}
        except Exception as exc:
            touch_cookie_poll(action="extracted_unverified", detail=str(exc)[:200])
            return {"status": "extracted_unverified", "detail": str(exc)[:200]}

    if result["status"] == "skipped":
        touch_cookie_poll(action="skipped", detail=result.get("detail", ""))
        return result

    touch_cookie_poll(action="failed", detail=result.get("detail", "CDP 提取失败")[:200])
    return {"status": "failed", "detail": result.get("detail", "")}


async def cookie_background_refresh_loop(stop: asyncio.Event) -> None:
    """后台轮询：AUTO_LOGIN_ENABLED 且配置 CDP 时，定时校验并在失效时提取。"""
    logger.info("Cookie 后台刷新任务已启动")
    try:
        while not stop.is_set():
            if not (settings.auto_login_enabled and settings.cookie_refresh_configured):
                touch_cookie_poll(action="disabled", detail="AUTO_LOGIN_ENABLED 未开启")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=60.0)
                continue

            poll_sec = max(60, int(settings.cookie_refresh_poll_seconds))
            touch_cookie_poll(action="scheduled", detail=f"每 {poll_sec // 60} 分钟检查")

            try:
                outcome = await run_cookie_background_refresh_once()
                logger.info(
                    "Cookie 后台刷新: %s — %s",
                    outcome.get("status"),
                    str(outcome.get("detail", ""))[:120],
                )
            except Exception as exc:
                logger.exception("Cookie 后台刷新异常")
                touch_cookie_poll(action="error", detail=str(exc)[:200])

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=float(poll_sec))
    except asyncio.CancelledError:
        logger.info("Cookie 后台刷新任务已停止")
        raise

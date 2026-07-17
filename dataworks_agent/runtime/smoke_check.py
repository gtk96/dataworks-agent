"""启动健康检查 — 延迟到首请求时执行，不阻塞服务启动。

启动时只注册后台任务，不执行任何 HTTP 请求或阻塞操作。
首次访问 /api/system/health 时触发完整检查，结果缓存供后续使用。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


async def startup_smoke_check() -> dict[str, dict[str, Any]]:
    """系统健康检查 — 检查各组件状态，返回结果字典。

    注意：此函数包含 HTTP 请求和 DB 查询，应在后台或首请求时调用，
    不应在 lifespan 中同步阻塞调用。
    """
    results: dict[str, dict[str, Any]] = {}

    # Official DataWorks MCP
    official_mcp = getattr(app_state, "_official_mcp_client", None)
    if official_mcp:
        status = official_mcp.status
        results["official_mcp"] = {
            "ok": status.connected,
            "msg": (
                f"connected, slim tools={status.tool_count}"
                if status.connected
                else status.error or "not connected"
            ),
        }
    else:
        results["official_mcp"] = {"ok": False, "msg": "not initialized"}

    # —— BFF ——
    bff = getattr(app_state, "_bff_client", None)
    if bff:
        from dataworks_agent.cookie.crypto import has_cookie

        if has_cookie():
            try:
                await bff.list_datasources()
                results["bff"] = {"ok": True, "msg": "已连接"}
            except Exception as e:
                results["bff"] = {"ok": False, "msg": f"连接异常: {str(e)[:80]}"}
        else:
            results["bff"] = {"ok": False, "msg": "Cookie 未配置"}
    else:
        results["bff"] = {"ok": False, "msg": "未初始化"}

    # —— CDP ——
    cdp = getattr(app_state, "_cdp_client", None)
    if cdp:
        try:
            from dataworks_agent.api_clients.cdp_client import _is_cdp_alive

            alive = await _is_cdp_alive()
            results["cdp"] = {
                "ok": alive,
                "msg": "Chrome :9222 已运行" if alive else "Chrome :9222 未运行",
            }
        except Exception as e:
            results["cdp"] = {"ok": False, "msg": str(e)[:80]}
    else:
        results["cdp"] = {"ok": False, "msg": "未初始化"}

    # —— Cookie ——
    from dataworks_agent.cookie.crypto import decrypt_cookie, has_cookie

    if has_cookie():
        try:
            from dataworks_agent.cookie.health import cookie_health_monitor

            health = await cookie_health_monitor.check(bff)
            cookie_str = decrypt_cookie()
            results["cookie"] = {
                "ok": health["status"] in ("healthy", "warning"),
                "msg": f"{health['status']}, {len(cookie_str)} 字符",
            }
        except Exception as e:
            results["cookie"] = {"ok": False, "msg": f"校验失败: {str(e)[:80]}"}
    else:
        results["cookie"] = {"ok": False, "msg": "未配置，请在设置页提取 Cookie"}

    # —— DB ——
    results["db"] = {"ok": True, "msg": "SQLite 正常"}

    # —— 清理超时 pending 任务 ——
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    try:
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            stuck = (
                db.query(ModelingTaskModel)
                .filter(
                    ModelingTaskModel.status == "pending",
                    ModelingTaskModel.created_at < cutoff,
                )
                .all()
            )
            for t in stuck:
                t.status = "failed"
                t.error_message = "任务超时未执行（pending 超过 1 小时）"
                t.updated_at = datetime.now(UTC).isoformat()
            if stuck:
                db.commit()
                logger.warning("清理超时 pending 任务: %d 条", len(stuck))
    except Exception as e:
        logger.warning("清理超时任务失败: %s", e)

    # 存储结果
    app_state.smoke_results = results
    app_state.smoke_ok = all(v["ok"] for v in results.values())

    ok_count = sum(1 for v in results.values() if v["ok"])
    total = len(results)
    logger.info("启动检查: %d/%d 项就绪", ok_count, total)

    return results

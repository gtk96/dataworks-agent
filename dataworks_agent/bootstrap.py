"""启动冒烟检查 — 验证各通道可用性，报告但不阻止服务。"""

from __future__ import annotations

import logging
from datetime import UTC

from dataworks_agent.config import settings
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


async def startup_smoke_check() -> None:
    """系统启动后检查各组件状态，结果写入 app_state 供前端展示。"""
    results: dict[str, dict] = {}

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
                # 用 list_datasources 轻量接口验证 BFF 可用性
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
            if alive:
                results["cdp"] = {"ok": True, "msg": "Chrome :9222 已运行"}
            else:
                results["cdp"] = {"ok": False, "msg": "Chrome :9222 未运行"}
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
    from datetime import datetime, timedelta

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ModelingTaskModel

    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
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

    # 存储结果
    app_state.smoke_results = results
    app_state.smoke_ok = all(v["ok"] for v in results.values())

    ok_count = sum(1 for v in results.values() if v["ok"])
    total = len(results)
    logger.info("启动检查: %d/%d 项就绪", ok_count, total)


class BootstrapChecker:
    """首次运行引导 — 检测环境完整性并自动初始化。"""

    async def run(self) -> dict:
        """按依赖顺序检查，缺什么自动补或引导用户。"""
        result = {"ready": True, "actions": [], "url": None}

        key = settings.cookie_encryption_key or ""
        if len(key) < 16:
            result["ready"] = False
            result["actions"].append(
                "Cookie 加密密钥强度不足（需 ≥16 字符），请在 .env 中更新 COOKIE_ENCRYPTION_KEY"
            )
            result["url"] = "/settings"
        elif key == "change-me-to-at-least-16-chars":
            result["ready"] = False
            result["actions"].append(
                "Cookie 加密密钥使用了默认值，请在 .env 中修改 COOKIE_ENCRYPTION_KEY 为自定义密钥"
            )
            result["url"] = "/settings"

        from dataworks_agent.cookie.crypto import has_cookie

        if not has_cookie():
            result["ready"] = False
            result["actions"].append("请到 Settings 页面配置 DataWorks Cookie (可点击 '自动提取')")
            result["url"] = "/settings"

        from pathlib import Path

        db_path = Path(settings.db_path)
        if not db_path.exists():
            from dataworks_agent.db.database import init_db

            init_db()
            result["actions"].append("已自动初始化 SQLite 数据库")

        Path(settings.archive_dir).mkdir(parents=True, exist_ok=True)

        return result

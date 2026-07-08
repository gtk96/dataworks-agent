"""TaskMonitor — 任务监控与告警。

功能：
1. 定期检查失败任务
2. 自动重跑可重试的任务
3. 发送告警通知（钉钉/日志）
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 可重试的错误类型
RETRYABLE_ERRORS = [
    "timeout",
    "connection_error",
    "rate_limit",
    "temporary_failure",
    "bff_error",
    "mcp_error",
]

# 不可重试的错误类型（支持下划线和空格格式）
NON_RETRYABLE_ERRORS = [
    "permission_denied",
    "permission denied",
    "sql_syntax_error",
    "sql syntax error",
    "table_already_exists",
    "table already exists",
    "root_check_failed",
    "root check failed",
    "validation_error",
    "validation error",
]

# 最大重试次数
MAX_AUTO_RETRIES = 2

# 监控间隔（秒）
MONITOR_INTERVAL = 300  # 5 分钟


class TaskMonitor:
    """任务监控器。"""

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动监控。"""
        if self._running:
            logger.warning("监控已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("任务监控已启动，间隔 %d 秒", MONITOR_INTERVAL)

    async def stop(self) -> None:
        """停止监控。"""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("任务监控已停止")

    async def _monitor_loop(self) -> None:
        """监控主循环。"""
        while self._running:
            try:
                await self._check_failed_tasks()
            except Exception as e:
                logger.error("监控检查失败: %s", e)

            await asyncio.sleep(MONITOR_INTERVAL)

    async def _check_failed_tasks(self) -> None:
        """检查失败的任务。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            # 查询失败的任务（最近 1 小时内）
            cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            failed_tasks = (
                db.query(ModelingTaskModel)
                .filter(
                    ModelingTaskModel.status == "failed",
                    ModelingTaskModel.updated_at >= cutoff,
                )
                .all()
            )

            if not failed_tasks:
                return

            logger.info("发现 %d 个失败任务", len(failed_tasks))

            for task in failed_tasks:
                await self._handle_failed_task(task)

    async def _handle_failed_task(self, task: Any) -> None:
        """处理失败的任务。"""
        error_msg = task.error_message or ""

        # 检查是否可重试
        if not self._is_retryable(error_msg):
            logger.info("任务 %s 不可重试: %s", task.task_id, error_msg[:50])
            await self._send_alert(task, "failed_non_retryable")
            return

        # 检查重试次数
        retry_count = self._get_retry_count(task)
        if retry_count >= MAX_AUTO_RETRIES:
            logger.info("任务 %s 已达最大重试次数: %d", task.task_id, retry_count)
            await self._send_alert(task, "max_retries_exceeded")
            return

        # 自动重试
        logger.info("自动重试任务 %s (第 %d 次)", task.task_id, retry_count + 1)
        await self._retry_task(task)

    def _is_retryable(self, error_msg: str) -> bool:
        """检查错误是否可重试。"""
        error_lower = error_msg.lower()

        # 先检查不可重试错误（优先级更高）
        for non_retryable in NON_RETRYABLE_ERRORS:
            if non_retryable in error_lower:
                return False

        # 再检查可重试错误
        for retryable in RETRYABLE_ERRORS:
            if retryable in error_lower:
                return True

        # 未知错误默认可重试
        return True

    def _get_retry_count(self, task: Any) -> int:
        """获取任务重试次数。"""
        import json

        try:
            steps = json.loads(task.steps_json) if task.steps_json else []
            retry_steps = [s for s in steps if s.get("step", "").startswith("retry_")]
            return len(retry_steps)
        except (json.JSONDecodeError, AttributeError):
            return 0

    async def _retry_task(self, task: Any) -> None:
        """重试任务。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            # 更新任务状态为 pending
            db_task = db.get(ModelingTaskModel, task.task_id)
            if db_task:
                db_task.status = "pending"
                db_task.error_message = ""
                db_task.updated_at = datetime.now(UTC).isoformat()

                # 记录重试步骤
                import json

                steps = json.loads(db_task.steps_json) if db_task.steps_json else []
                steps.append(
                    {
                        "step": f"retry_{datetime.now(UTC).isoformat()}",
                        "status": "ok",
                        "message": "自动重试",
                    }
                )
                db_task.steps_json = json.dumps(steps)

                db.commit()
                logger.info("任务 %s 已重置为 pending", task.task_id)

        # 触发任务执行（通过队列或直接执行）
        await self._trigger_task_execution(task.task_id)

    async def _trigger_task_execution(self, task_id: str) -> None:
        """触发任务执行。"""
        # 这里可以集成到现有的任务队列
        # 目前只记录日志
        logger.info("任务 %s 已加入执行队列", task_id)

    async def _send_alert(self, task: Any, alert_type: str) -> None:
        """发送告警通知。"""
        from dataworks_agent.config import settings

        # 构建告警消息
        message = self._build_alert_message(task, alert_type)

        # 记录日志
        logger.warning("告警: %s", message)

        # 如果配置了钉钉机器人，发送钉钉通知
        if hasattr(settings, "dingtalk_webhook") and settings.dingtalk_webhook:
            await self._send_dingtalk_alert(message)

    def _build_alert_message(self, task: Any, alert_type: str) -> str:
        """构建告警消息。"""
        alerts = {
            "failed_non_retryable": f"任务 {task.task_id} 失败（不可重试）: {task.error_message[:100]}",
            "max_retries_exceeded": f"任务 {task.task_id} 已达最大重试次数",
            "auto_retry": f"任务 {task.task_id} 正在自动重试",
        }
        return alerts.get(alert_type, f"任务 {task.task_id} 状态异常")

    async def _send_dingtalk_alert(self, message: str) -> None:
        """发送钉钉告警。"""
        import httpx

        from dataworks_agent.config import settings

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    settings.dingtalk_webhook,
                    json={"msgtype": "text", "text": {"content": message}},
                )
                logger.info("钉钉告警已发送")
        except Exception as e:
            logger.error("钉钉告警发送失败: %s", e)


# 全局监控实例
task_monitor = TaskMonitor()

"""Autonomous Agent 主入口 — 组合 planner / security_guard / executor / verifier。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.agent.autonomous.executor import AutonomousExecutor
from dataworks_agent.agent.autonomous.planner import AutonomousPlanner
from dataworks_agent.agent.autonomous.security_guard import SecurityViolationError
from dataworks_agent.agent.autonomous.state import (
    AutonomousContext,
    AutonomousTask,
    ExecutionStatus,
)
from dataworks_agent.agent.autonomous.verifier import AutonomousVerifier

logger = logging.getLogger(__name__)


class AutonomousAgent:
    """DataWorks 数仓自主执行 Agent。

    流程：
    1. 接收用户意图 + 参数
    2. Security Guard 预检
    3. Planner 生成任务计划
    4. Executor 逐步执行
    5. Verifier 验证结果
    6. 返回 AutonomousTask（含状态、步骤结果、验证结果）
    """

    def __init__(
        self,
        context: AutonomousContext,
        openapi_client: Any,
        modeling_engine: Any,
    ) -> None:
        self._context = context
        self._planner = AutonomousPlanner(context)
        self._security_guard = _build_security_guard(context)
        self._executor = AutonomousExecutor(openapi_client, modeling_engine)
        self._verifier = AutonomousVerifier(openapi_client)

    async def process_request(self, intent: str, params: dict[str, Any]) -> AutonomousTask:
        """处理用户请求，完整走规划→执行→验证流程。

        Args:
            intent: 用户自然语言意图，如 "帮我建一张 ODS 表"。
            params: 结构化参数，如 target_table、source_table 等。

        Returns:
            执行完成的 AutonomousTask。

        Raises:
            SecurityViolationError: 安全守卫拦截。
            ValueError: 意图无法识别。
        """
        logger.info("AutonomousAgent 收到请求: intent=%s, params=%s", intent, params)

        # Step 1: 规划
        task = self._planner.generate_plan(intent, params)
        logger.info("任务已规划: %s, 步骤数=%d", task.id, len(task.plan))

        # Step 2: 安全预检
        try:
            await self._security_guard.validate_request(task.task_type, task.params)
        except SecurityViolationError as exc:
            task.mark_failed(f"安全守卫拦截: {exc}")
            logger.warning("安全守卫拦截任务 %s: %s", task.id, exc)
            return task

        # Step 3: 执行
        executed = await self._executor.execute_task(task)
        if not executed:
            logger.error("任务 %s 执行失败: %s", task.id, task.error_message)
            return task

        # Step 4: 验证
        try:
            verification = await self._verifier.verify_task(task)
            logger.info(
                "任务 %s 验证: success=%s, summary=%s",
                task.id,
                verification.success,
                verification.summary,
            )
        except Exception as exc:
            logger.exception("任务 %s 验证失败: %s", task.id, exc)
            task.mark_failed(f"验证阶段异常: {exc}")
            return task

        if not verification.success:
            task.mark_failed(verification.summary)
        else:
            task.status = ExecutionStatus.VERIFIED

        return task

    async def retry_task(self, task: AutonomousTask) -> AutonomousTask:
        """重试失败任务。

        仅允许重试处于 FAILED 状态的任务，且不会重新经过安全守卫。
        """
        if task.status != ExecutionStatus.FAILED:
            logger.warning("任务 %s 当前状态为 %s，不支持重试", task.id, task.status)
            return task

        logger.info("重试任务 %s: %s", task.id, task.description)
        task.error_message = None
        task.step_results.clear()

        executed = await self._executor.execute_task(task)
        if not executed:
            return task

        try:
            verification = await self._verifier.verify_task(task)
            if verification.success:
                task.status = ExecutionStatus.VERIFIED
            else:
                task.mark_failed(verification.summary)
        except Exception as exc:
            task.mark_failed(f"验证阶段异常: {exc}")

        return task


def _build_security_guard(context: AutonomousContext) -> Any:
    """延迟导入 security_guard，避免循环依赖。"""
    from dataworks_agent.agent.autonomous.security_guard import AutonomousSecurityGuard

    return AutonomousSecurityGuard(context)

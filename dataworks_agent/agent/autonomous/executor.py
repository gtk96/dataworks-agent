"""任务执行器 — 逐步执行 AutonomousTask 中的计划步骤。"""

from __future__ import annotations

import logging
import time
from typing import Any

from dataworks_agent.agent.autonomous.state import (
    AutonomousTask,
    ExecutionStatus,
    StepResult,
)

logger = logging.getLogger(__name__)


class AutonomousExecutor:
    """按步骤链驱动任务执行，集成现有 ModelingEngine 与 API Clients。

    当前阶段具体实现以 pass/return True 占位，保证架构清晰、接口稳定，
    后续接入真实 OpenAPI / MaxCompute / BFF 能力。
    """

    def __init__(self, openapi_client: Any, modeling_engine: Any) -> None:
        self._openapi_client = openapi_client
        self._modeling_engine = modeling_engine

    async def execute_task(self, task: AutonomousTask) -> bool:
        """按 plan 顺序逐步执行任务。

        Returns:
            True 表示所有步骤均成功；False 表示中途失败。
        """
        if task.status == ExecutionStatus.VERIFIED:
            logger.info("任务 %s 已通过验证，跳过重复执行", task.id)
            return True

        task.mark_executing()
        logger.info("开始执行任务 %s (%s): %s 步", task.id, task.task_type, len(task.plan))

        for idx, step_def in enumerate(task.plan):
            step_name = step_def.get("step", f"step_{idx}")
            logger.info("执行步骤 [%d/%d]: %s", idx + 1, len(task.plan), step_name)
            started = time.monotonic()

            try:
                success = await self.execute_step(task, step_def)
            except Exception as exc:
                elapsed = (time.monotonic() - started) * 1000
                result = StepResult(
                    step=step_name,
                    status="failed",
                    error=str(exc),
                    duration_ms=elapsed,
                )
                task.add_step_result(result)
                task.mark_failed(f"步骤 {step_name} 执行异常: {exc}")
                logger.exception("任务 %s 步骤 %s 失败: %s", task.id, step_name, exc)
                return False

            elapsed = (time.monotonic() - started) * 1000
            result = StepResult(
                step=step_name,
                status="completed" if success else "failed",
                details=step_def.get("details", {}),
                duration_ms=elapsed,
            )
            task.add_step_result(result)

            if not success:
                task.mark_failed(f"步骤 {step_name} 返回失败")
                logger.warning("任务 %s 步骤 %s 失败，停止执行", task.id, step_name)
                return False

        logger.info("任务 %s 全部步骤完成", task.id)
        return True

    async def execute_step(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """执行单个步骤。

        每个 step 的 handler 按 step["step"] 名称分派。
        未实现的步骤返回 False 并记录 warning。
        """
        handler_name = step.get("step", "")

        handlers: dict[str, Any] = {
            "validate_params": self._handle_validate_params,
            "generate_ddl": self._handle_generate_ddl,
            "create_table": self._handle_create_table,
            "create_node": self._handle_create_node,
            "configure_schedule": self._handle_configure_schedule,
            "configure_dependencies": self._handle_configure_dependencies,
            "discover_source_tables": self._handle_discover_source_tables,
            "generate_sql": self._handle_generate_sql,
            "read_current": self._handle_read_current,
            "apply_change": self._handle_apply_change,
            "apply_schedule": self._handle_apply_schedule,
            "apply_dependency": self._handle_apply_dependency,
            "verify": self._handle_verify_placeholder,
        }

        handler = handlers.get(handler_name)
        if handler is None:
            logger.warning("未知步骤类型: %s，跳过", handler_name)
            return True

        return await handler(task, step)

    # ── ODS 步骤处理器（占位） ──

    async def _handle_validate_params(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """校验参数 — 基础非空检查。"""
        params = task.params
        target = params.get("target_table")
        if not target:
            logger.warning("ODS/DWD 任务缺少 target_table 参数")
            return False
        return True

    async def _handle_generate_ddl(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """生成 DDL — 待接入 DDLGenerator。"""
        logger.debug("DDL 生成步骤（占位）: %s", task.id)
        return True

    async def _handle_create_table(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """MaxCompute 建表 — 待接入 execute_ddl。"""
        logger.debug("建表步骤（占位）: %s", task.id)
        return True

    async def _handle_create_node(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """创建 DataWorks 节点 — 待接入 OpenAPI create_node。"""
        logger.debug("建节点步骤（占位）: %s", task.id)
        return True

    async def _handle_configure_schedule(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """配置调度 — 待接入 UpdateNodeSchedule。"""
        logger.debug("调度配置步骤（占位）: %s", task.id)
        return True

    async def _handle_configure_dependencies(
        self, task: AutonomousTask, step: dict[str, Any]
    ) -> bool:
        """配置依赖 — 待接入 UpdateWorkflowDependencies。"""
        logger.debug("依赖配置步骤（占位）: %s", task.id)
        return True

    # ── DWD 特有步骤处理器（占位） ──

    async def _handle_discover_source_tables(
        self, task: AutonomousTask, step: dict[str, Any]
    ) -> bool:
        """发现源表 — 待接入 TableDiscovery。"""
        logger.debug("源表发现步骤（占位）: %s", task.id)
        return True

    async def _handle_generate_sql(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """生成 DWD SQL/DML — 待接入 DMLGenerator。"""
        logger.debug("SQL 生成步骤（占位）: %s", task.id)
        return True

    # ── 修改 / 调度 / 依赖步骤处理器（占位） ──

    async def _handle_read_current(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """读取当前配置 — 待接入 GetNode / GetNodeSchedule。"""
        logger.debug("读取当前步骤（占位）: %s", task.id)
        return True

    async def _handle_apply_change(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """应用变更 — 待接入 UpdateNode。"""
        logger.debug("应用变更步骤（占位）: %s", task.id)
        return True

    async def _handle_apply_schedule(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """应用调度变更 — 待接入 UpdateNodeSchedule。"""
        logger.debug("应用调度步骤（占位）: %s", task.id)
        return True

    async def _handle_apply_dependency(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """应用依赖变更 — 待接入 UpdateWorkflowDependencies。"""
        logger.debug("应用依赖步骤（占位）: %s", task.id)
        return True

    async def _handle_verify_placeholder(self, task: AutonomousTask, step: dict[str, Any]) -> bool:
        """验证步骤占位 — 真实逻辑由 AutonomousVerifier 承担。"""
        logger.debug("验证步骤（占位）: %s", task.id)
        return True

"""结果验证器 — 验证 AutonomousTask 执行后的表/节点/调度/依赖状态。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.agent.autonomous.state import (
    AutonomousTask,
    ExecutionStatus,
    VerifierResult,
)

logger = logging.getLogger(__name__)


class AutonomousVerifier:
    """执行后验证器。

    当前阶段仅实现结构骨架：逐项检查以 mock 形式返回 passed，
    后续接入真实 OpenAPI list_nodes / get_node / list_node_dependencies 等。
    """

    def __init__(self, openapi_client: Any) -> None:
        self._openapi_client = openapi_client

    async def verify_task(self, task: AutonomousTask) -> VerifierResult:
        """根据任务类型路由到对应的验证方法。"""
        if task.task_type.value == "create_ods":
            return await self._verify_ods_creation(task)
        if task.task_type.value == "create_dwd":
            return await self._verify_dwd_creation(task)
        if task.task_type.value == "modify_task":
            return await self._verify_modify_task(task)
        if task.task_type.value == "configure_schedule":
            return await self._verify_schedule(task)
        if task.task_type.value == "configure_dependency":
            return await self._verify_dependency(task)

        return VerifierResult(
            success=False,
            checks=[],
            summary=f"未知任务类型: {task.task_type}",
        )

    async def _verify_ods_creation(self, task: AutonomousTask) -> VerifierResult:
        """验证 ODS 创建结果：表存在、节点存在、调度已配置。"""
        checks: list[dict[str, Any]] = []
        warnings: list[str] = []

        target = task.params.get("target_table", "")
        checks.append(
            {
                "name": "table_exists",
                "passed": True,
                "severity": "info",
                "message": f"ODS 表 {target} 已创建（mock）",
            }
        )
        checks.append(
            {
                "name": "node_exists",
                "passed": True,
                "severity": "info",
                "message": "DI/Holo 节点已创建（mock）",
            }
        )
        checks.append(
            {
                "name": "schedule_configured",
                "passed": True,
                "severity": "info",
                "message": "调度周期已配置（mock）",
            }
        )

        task.verification_result = {
            "success": True,
            "checks": checks,
            "summary": "ODS 创建验证通过",
        }
        task.status = ExecutionStatus.VERIFIED
        return VerifierResult(
            success=True,
            checks=checks,
            summary="ODS 创建验证通过",
            warnings=warnings,
        )

    async def _verify_dwd_creation(self, task: AutonomousTask) -> VerifierResult:
        """验证 DWD 创建结果：表存在、节点存在、依赖已配置、调度已配置。"""
        checks: list[dict[str, Any]] = []
        warnings: list[str] = []

        target = task.params.get("target_table", "")
        checks.append(
            {
                "name": "table_exists",
                "passed": True,
                "severity": "info",
                "message": f"DWD 表 {target} 已创建（mock）",
            }
        )
        checks.append(
            {
                "name": "node_exists",
                "passed": True,
                "severity": "info",
                "message": "SQL 节点已创建（mock）",
            }
        )
        checks.append(
            {
                "name": "dependencies_configured",
                "passed": True,
                "severity": "info",
                "message": "节点级上游依赖已配置（mock）",
            }
        )
        checks.append(
            {
                "name": "schedule_configured",
                "passed": True,
                "severity": "info",
                "message": "调度周期与自依赖已配置（mock）",
            }
        )

        task.verification_result = {
            "success": True,
            "checks": checks,
            "summary": "DWD 创建验证通过",
        }
        task.status = ExecutionStatus.VERIFIED
        return VerifierResult(
            success=True,
            checks=checks,
            summary="DWD 创建验证通过",
            warnings=warnings,
        )

    async def _verify_modify_task(self, task: AutonomousTask) -> VerifierResult:
        """验证任务修改结果。"""
        checks: list[dict[str, Any]] = []
        target = task.params.get("target_table") or task.params.get("node_id", "unknown")
        checks.append(
            {
                "name": "node_updated",
                "passed": True,
                "severity": "info",
                "message": f"节点 {target} 已更新（mock）",
            }
        )
        return VerifierResult(
            success=True,
            checks=checks,
            summary=f"任务修改验证通过: {target}",
        )

    async def _verify_schedule(self, task: AutonomousTask) -> VerifierResult:
        """验证调度配置结果。"""
        checks: list[dict[str, Any]] = []
        target = task.params.get("target_table") or task.params.get("node_id", "unknown")
        checks.append(
            {
                "name": "schedule_applied",
                "passed": True,
                "severity": "info",
                "message": f"调度配置已应用到 {target}（mock）",
            }
        )
        return VerifierResult(
            success=True,
            checks=checks,
            summary=f"调度配置验证通过: {target}",
        )

    async def _verify_dependency(self, task: AutonomousTask) -> VerifierResult:
        """验证依赖配置结果。"""
        checks: list[dict[str, Any]] = []
        target = task.params.get("target_table") or task.params.get("node_id", "unknown")
        checks.append(
            {
                "name": "dependencies_applied",
                "passed": True,
                "severity": "info",
                "message": f"依赖关系已应用到 {target}（mock）",
            }
        )
        return VerifierResult(
            success=True,
            checks=checks,
            summary=f"依赖配置验证通过: {target}",
        )

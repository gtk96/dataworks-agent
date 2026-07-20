"""结果验证器 — 通过真实 API 调用验证表/节点/调度/依赖状态。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.agent.autonomous.state import (
    AutonomousTask,
    ExecutionStatus,
    VerifierResult,
)

logger = logging.getLogger(__name__)


def _get_maxcompute_client() -> Any:
    from dataworks_agent.state import app_state

    return app_state._maxcompute_client


def _get_node_client() -> Any:
    from dataworks_agent.state import app_state

    return app_state._node_client


class AutonomousVerifier:
    """执行后验证器 — 通过真实 API 调用回查表、节点、调度、依赖状态。"""

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

    async def _check_table_exists(self, target: str) -> dict[str, Any]:
        """检查 MaxCompute 表是否存在。"""
        mc = _get_maxcompute_client()
        if mc is None:
            return {
                "name": "table_exists",
                "passed": False,
                "severity": "error",
                "message": "MaxComputeClient 未初始化，无法验证表是否存在",
            }

        exists = await mc.table_exists(target)
        return {
            "name": "table_exists",
            "passed": exists,
            "severity": "error" if not exists else "info",
            "message": f"表 {target} {'存在' if exists else '不存在'}",
        }

    async def _check_node_exists(self, task: AutonomousTask) -> dict[str, Any]:
        """检查 DataWorks 节点是否存在。"""
        node_id = task.params.get("_node_id")
        if not node_id:
            return {
                "name": "node_exists",
                "passed": False,
                "severity": "error",
                "message": "节点 ID 未记录（create_node 步骤未执行或未成功）",
            }

        node_client = _get_node_client()
        if node_client is None:
            return {
                "name": "node_exists",
                "passed": False,
                "severity": "error",
                "message": "OpenAPINodeAdapter 未初始化，无法验证节点",
            }

        try:
            spec = await node_client._load_spec(node_id)
            exists = spec is not None
        except Exception as exc:
            exists = False
            logger.warning("节点验证异常: node=%s, error=%s", node_id, exc)

        return {
            "name": "node_exists",
            "passed": exists,
            "severity": "error" if not exists else "info",
            "message": f"节点 {node_id} {'存在' if exists else '不存在'}",
        }

    async def _check_schedule_configured(self, task: AutonomousTask) -> dict[str, Any]:
        """检查节点调度是否已配置（trigger.cron 非空）。"""
        node_id = task.params.get("_node_id")
        if not node_id:
            return {
                "name": "schedule_configured",
                "passed": False,
                "severity": "warning",
                "message": "节点 ID 未记录，无法验证调度",
            }

        node_client = _get_node_client()
        if node_client is None:
            return {
                "name": "schedule_configured",
                "passed": False,
                "severity": "warning",
                "message": "OpenAPINodeAdapter 未初始化，无法验证调度",
            }

        try:
            spec = await node_client._load_spec(node_id)
            if spec is None:
                return {
                    "name": "schedule_configured",
                    "passed": False,
                    "severity": "warning",
                    "message": f"无法读取节点 spec: {node_id}",
                }

            nodes = spec.get("spec", {}).get("nodes", [])
            trigger = nodes[0].get("trigger", {}) if nodes else {}
            cron = trigger.get("cron", "")
            configured = bool(cron)
        except Exception as exc:
            configured = False
            logger.warning("调度验证异常: node=%s, error=%s", node_id, exc)

        return {
            "name": "schedule_configured",
            "passed": configured,
            "severity": "warning" if not configured else "info",
            "message": f"调度 {'已配置' if configured else '未配置'}"
            + (f" (cron={cron})" if configured else ""),
        }

    async def _check_dependencies_configured(self, task: AutonomousTask) -> dict[str, Any]:
        """检查节点依赖是否已配置（flow.depends 非空）。"""
        node_id = task.params.get("_node_id")
        if not node_id:
            return {
                "name": "dependencies_configured",
                "passed": False,
                "severity": "warning",
                "message": "节点 ID 未记录，无法验证依赖",
            }

        node_client = _get_node_client()
        if node_client is None:
            return {
                "name": "dependencies_configured",
                "passed": False,
                "severity": "warning",
                "message": "OpenAPINodeAdapter 未初始化，无法验证依赖",
            }

        try:
            spec = await node_client._load_spec(node_id)
            if spec is None:
                return {
                    "name": "dependencies_configured",
                    "passed": False,
                    "severity": "warning",
                    "message": f"无法读取节点 spec: {node_id}",
                }

            flow = spec.get("spec", {}).get("flow", [])
            depends = flow[0].get("depends", []) if flow else []
            configured = len(depends) > 0
        except Exception as exc:
            configured = False
            logger.warning("依赖验证异常: node=%s, error=%s", node_id, exc)

        return {
            "name": "dependencies_configured",
            "passed": configured,
            "severity": "warning" if not configured else "info",
            "message": f"依赖 {'已配置' if configured else '未配置'}"
            + (f" ({len(depends)} 条)" if configured else ""),
        }

    async def _verify_ods_creation(self, task: AutonomousTask) -> VerifierResult:
        """验证 ODS 创建结果：表存在、节点存在、调度已配置。"""
        target = task.params.get("target_table", "")

        checks = [
            await self._check_table_exists(target),
            await self._check_node_exists(task),
            await self._check_schedule_configured(task),
        ]

        all_passed = all(c["passed"] for c in checks)
        summary = "ODS 创建验证" + ("通过" if all_passed else "未完全通过")

        task.verification_result = {
            "success": all_passed,
            "checks": checks,
            "summary": summary,
        }
        if all_passed:
            task.status = ExecutionStatus.VERIFIED

        return VerifierResult(
            success=all_passed,
            checks=checks,
            summary=summary,
        )

    async def _verify_dwd_creation(self, task: AutonomousTask) -> VerifierResult:
        """验证 DWD 创建结果：表存在、节点存在、依赖已配置、调度已配置。"""
        target = task.params.get("target_table", "")

        checks = [
            await self._check_table_exists(target),
            await self._check_node_exists(task),
            await self._check_dependencies_configured(task),
            await self._check_schedule_configured(task),
        ]

        all_passed = all(c["passed"] for c in checks)
        summary = "DWD 创建验证" + ("通过" if all_passed else "未完全通过")

        task.verification_result = {
            "success": all_passed,
            "checks": checks,
            "summary": summary,
        }
        if all_passed:
            task.status = ExecutionStatus.VERIFIED

        return VerifierResult(
            success=all_passed,
            checks=checks,
            summary=summary,
        )

    async def _verify_modify_task(self, task: AutonomousTask) -> VerifierResult:
        """验证任务修改结果。"""
        node_id = task.params.get("node_id") or task.params.get("_node_id", "")
        checks = [await self._check_node_exists(task)]
        all_passed = all(c["passed"] for c in checks)

        return VerifierResult(
            success=all_passed,
            checks=checks,
            summary=f"任务修改验证{'通过' if all_passed else '未通过'}: {node_id}",
        )

    async def _verify_schedule(self, task: AutonomousTask) -> VerifierResult:
        """验证调度配置结果。"""
        checks = [await self._check_schedule_configured(task)]
        all_passed = all(c["passed"] for c in checks)

        return VerifierResult(
            success=all_passed,
            checks=checks,
            summary=f"调度配置验证{'通过' if all_passed else '未通过'}",
        )

    async def _verify_dependency(self, task: AutonomousTask) -> VerifierResult:
        """验证依赖配置结果。"""
        checks = [await self._check_dependencies_configured(task)]
        all_passed = all(c["passed"] for c in checks)

        return VerifierResult(
            success=all_passed,
            checks=checks,
            summary=f"依赖配置验证{'通过' if all_passed else '未通过'}",
        )

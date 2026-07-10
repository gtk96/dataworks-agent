"""任务执行器"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.executor.tool_executor import ToolExecutor
from dataworks_agent.agent.planner.task_planner import TaskPlan

logger = logging.getLogger("dataworks_agent.agent.executor")


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    task_id: str
    step_results: list[StepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TaskExecutor:
    """任务执行器"""

    def __init__(self):
        self._tool_executor = ToolExecutor()

    def execute(self, plan: TaskPlan) -> ExecutionResult:
        """执行任务计划"""
        step_results: list[StepResult] = []
        errors: list[str] = []

        # 按依赖顺序执行
        executed: set[str] = set()

        for step in plan.steps:
            # 检查依赖
            if not all(dep in executed for dep in step.depends_on):
                error = f"步骤 {step.step_id} 依赖未满足"
                errors.append(error)
                step_results.append(StepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    success=False,
                    error=error,
                ))
                continue

            # 执行步骤
            logger.info(f"执行步骤 {step.step_id}: {step.tool}")
            tool_result = self._tool_executor.execute(step.tool, step.params)

            step_result = StepResult(
                step_id=step.step_id,
                tool=step.tool,
                success=tool_result.success,
                data=tool_result.data,
                error=tool_result.error,
            )
            step_results.append(step_result)

            if tool_result.success:
                executed.add(step.step_id)
            else:
                errors.append(f"步骤 {step.step_id} 执行失败: {tool_result.error}")

        return ExecutionResult(
            success=len(errors) == 0,
            task_id=plan.task_id,
            step_results=step_results,
            errors=errors,
        )

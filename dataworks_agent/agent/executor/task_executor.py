"""任务执行器"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.executor.tool_executor import ToolExecutor, ToolResult
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

    def __init__(self, max_retries: int = 3):
        self._tool_executor = ToolExecutor()
        self._max_retries = max_retries

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

            # 执行步骤（带重试）
            logger.info("执行步骤 %s: %s", step.step_id, step.tool)
            tool_result = self._execute_with_retry(step)

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

    def _execute_with_retry(self, step: Any) -> ToolResult:
        """带重试的执行"""
        last_result = None

        for attempt in range(self._max_retries):
            result = self._tool_executor.execute(step.tool, step.params)
            if result.success:
                return result

            last_result = result

            # 检查是否应该重试
            if attempt < self._max_retries - 1 and self._should_retry(result.error):
                delay = 2 ** attempt  # 指数退避
                logger.info(
                    "步骤 %s 失败，%d秒后重试 (尝试 %d/%d)",
                    step.step_id, delay, attempt + 1, self._max_retries
                )
                time.sleep(delay)

        return last_result  # 返回最后一次结果

    def _should_retry(self, error: str | None) -> bool:
        """判断是否应该重试"""
        if not error:
            return False

        # 瞬时错误应该重试
        transient_errors = [
            "connection_timeout",
            "throttling",
            "rate_limit",
            "timeout",
        ]

        error_lower = error.lower()
        return any(transient_error in error_lower for transient_error in transient_errors)

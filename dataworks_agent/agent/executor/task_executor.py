"""Task executor for Agent plans."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from dataworks_agent.agent.executor.tool_executor import ToolExecutor, ToolResult
from dataworks_agent.agent.monitor.execution_monitor import ExecutionMonitor, ExecutionStatus
from dataworks_agent.agent.planner.task_planner import TaskPlan

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of one planned step."""

    step_id: str
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "warnings": self.warnings,
        }


@dataclass
class ExecutionResult:
    """Result of executing a TaskPlan."""

    success: bool
    task_id: str
    step_results: list[StepResult]
    errors: list[str] = field(default_factory=list)
    status: ExecutionStatus | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "task_id": self.task_id,
            "step_results": [step.to_dict() for step in self.step_results],
            "errors": self.errors,
            "status": self.status.to_dict() if self.status else None,
        }


class _PlanExecutionState(TypedDict):
    index: int
    executed: set[str]
    step_results: list[StepResult]
    errors: list[str]


class TaskExecutor:
    """Execute a TaskPlan step by step with lightweight retry support."""

    def __init__(self, max_retries: int = 3, monitor: ExecutionMonitor | None = None):
        self._tool_executor = ToolExecutor()
        self._max_retries = max_retries
        self._monitor = monitor or ExecutionMonitor()

    @property
    def monitor(self) -> ExecutionMonitor:
        """Execution monitor used by this executor."""
        return self._monitor

    def execute(self, plan: TaskPlan) -> ExecutionResult:
        """Execute a plan through a LangGraph state machine."""
        self._monitor.start_task(plan.task_id, plan.steps)

        def execute_next(state: _PlanExecutionState) -> dict[str, Any]:
            index = state["index"]
            step = plan.steps[index]
            executed = set(state["executed"])
            step_results = list(state["step_results"])
            errors = list(state["errors"])

            if not all(dep in executed for dep in step.depends_on):
                error = f"Step {step.step_id} dependency is not complete"
                errors.append(error)
                self._monitor.record_step_complete(plan.task_id, step.step_id, False, error=error)
                step_results.append(
                    StepResult(
                        step_id=step.step_id,
                        tool=step.tool,
                        success=False,
                        error=error,
                    )
                )
                return {
                    "index": index + 1,
                    "executed": executed,
                    "step_results": step_results,
                    "errors": errors,
                }

            logger.info("Executing Agent step %s: %s", step.step_id, step.tool)
            self._monitor.record_step_start(
                plan.task_id,
                step.step_id,
                step.tool,
                title=step.title,
                phase=step.phase,
            )
            tool_result = self._execute_with_retry(step)
            self._monitor.record_step_complete(
                plan.task_id,
                step.step_id,
                tool_result.success,
                error=tool_result.error,
                data=tool_result.data,
                warnings=tool_result.warnings,
            )
            step_results.append(
                StepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    success=tool_result.success,
                    data=tool_result.data,
                    error=tool_result.error,
                    warnings=tool_result.warnings,
                )
            )
            if tool_result.success:
                executed.add(step.step_id)
            else:
                errors.append(f"Step {step.step_id} failed: {tool_result.error}")
            return {
                "index": index + 1,
                "executed": executed,
                "step_results": step_results,
                "errors": errors,
            }

        def route_next(state: _PlanExecutionState) -> str:
            return "done" if state["index"] >= len(plan.steps) else "next"

        builder = StateGraph(_PlanExecutionState)
        builder.add_node("execute_step", execute_next)
        builder.add_edge(START, "execute_step")
        builder.add_conditional_edges(
            "execute_step",
            route_next,
            {"next": "execute_step", "done": END},
        )
        graph = builder.compile()
        final_state = graph.invoke(
            {"index": 0, "executed": set(), "step_results": [], "errors": []}
        )

        self._monitor.complete_task(plan.task_id)
        status = self._monitor.get_status(plan.task_id)
        errors = final_state["errors"]
        return ExecutionResult(
            success=len(errors) == 0,
            task_id=plan.task_id,
            step_results=final_state["step_results"],
            errors=errors,
            status=status,
        )

    def _execute_with_retry(self, step: Any) -> ToolResult:
        """Execute one step with retry for transient failures."""
        last_result: ToolResult | None = None

        for attempt in range(self._max_retries):
            result = self._tool_executor.execute(step.tool, step.params)
            if result.success:
                return result

            last_result = result
            if attempt < self._max_retries - 1 and self._should_retry(result.error):
                delay = 2**attempt
                logger.info(
                    "Retrying Agent step %s in %d seconds (attempt %d/%d)",
                    step.step_id,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(delay)

        return last_result or ToolResult(tool=step.tool, success=False, error="unknown_error")

    def _should_retry(self, error: str | None) -> bool:
        """Return whether an error is likely transient."""
        if not error:
            return False
        transient_errors = ["connection_timeout", "throttling", "rate_limit", "timeout"]
        error_lower = error.lower()
        return any(transient_error in error_lower for transient_error in transient_errors)

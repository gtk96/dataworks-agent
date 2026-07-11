"""Execution monitor for Agent task progress."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepStatus:
    """Runtime status of one Agent step."""

    step_id: str
    tool: str
    status: str  # pending, running, completed, failed, skipped
    title: str = ""
    phase: str = "execute"
    start_time: float | None = None
    end_time: float | None = None
    error: str | None = None
    data: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "status": self.status,
            "title": self.title or self.tool,
            "phase": self.phase,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error": self.error,
            "data": self.data,
            "warnings": self.warnings,
        }


@dataclass
class ExecutionStatus:
    """Runtime status of an Agent task."""

    task_id: str
    current_step: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    steps: dict[str, StepStatus] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "steps": {key: step.to_dict() for key, step in self.steps.items()},
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class ExecutionMonitor:
    """In-memory monitor for Agent task execution."""

    def __init__(self) -> None:
        self._statuses: dict[str, ExecutionStatus] = {}

    def start_task(self, task_id: str, steps: list[Any]) -> None:
        """Create a task status record with all planned steps pending."""
        status = ExecutionStatus(
            task_id=task_id,
            total_steps=len(steps),
            start_time=time.time(),
            steps={
                step.step_id: StepStatus(
                    step_id=step.step_id,
                    tool=step.tool,
                    title=getattr(step, "title", "") or step.tool,
                    phase=getattr(step, "phase", "execute"),
                    status="pending",
                )
                for step in steps
            },
        )
        self._statuses[task_id] = status

    def record_step_start(
        self,
        task_id: str,
        step_id: str,
        tool: str,
        *,
        title: str = "",
        phase: str = "execute",
    ) -> None:
        """Mark a step as running."""
        if task_id not in self._statuses:
            self._statuses[task_id] = ExecutionStatus(
                task_id=task_id,
                total_steps=1,
                start_time=time.time(),
            )

        status = self._statuses[task_id]
        if status.start_time is None:
            status.start_time = time.time()
        if step_id not in status.steps:
            status.steps[step_id] = StepStatus(step_id=step_id, tool=tool, status="pending")
            status.total_steps = max(status.total_steps, len(status.steps))

        step = status.steps[step_id]
        step.tool = tool
        step.title = title or step.title or tool
        step.phase = phase or step.phase
        step.status = "running"
        step.start_time = time.time()
        status.current_step = step_id

    def record_step_complete(
        self,
        task_id: str,
        step_id: str,
        success: bool,
        error: str | None = None,
        data: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Mark a step as completed or failed."""
        if task_id not in self._statuses:
            return

        status = self._statuses[task_id]
        if step_id in status.steps:
            step = status.steps[step_id]
            previous_status = step.status
            step.status = "completed" if success else "failed"
            step.end_time = time.time()
            step.error = error
            step.data = data
            step.warnings = warnings or []

            if previous_status not in {"completed", "failed"}:
                if success:
                    status.completed_steps += 1
                else:
                    status.failed_steps += 1
            finished_steps = status.completed_steps + status.failed_steps
            status.current_step = (
                None if finished_steps >= status.total_steps else status.current_step
            )

    def get_status(self, task_id: str) -> ExecutionStatus | None:
        """Return a task status by id."""
        return self._statuses.get(task_id)

    def complete_task(self, task_id: str) -> None:
        """Mark a task as finished."""
        if task_id in self._statuses:
            self._statuses[task_id].end_time = time.time()
            self._statuses[task_id].current_step = None

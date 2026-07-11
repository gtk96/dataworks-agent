"""执行监控器 - 跟踪任务执行状态"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StepStatus:
    """步骤状态"""
    step_id: str
    tool: str
    status: str  # pending, running, completed, failed
    start_time: float | None = None
    end_time: float | None = None
    error: str | None = None


@dataclass
class ExecutionStatus:
    """执行状态"""
    task_id: str
    current_step: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    steps: dict[str, StepStatus] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None


class ExecutionMonitor:
    """执行监控器"""
    
    def __init__(self):
        self._statuses: dict[str, ExecutionStatus] = {}
    
    def record_step_start(self, task_id: str, step_id: str, tool: str) -> None:
        """记录步骤开始"""
        if task_id not in self._statuses:
            self._statuses[task_id] = ExecutionStatus(task_id=task_id)
        
        status = self._statuses[task_id]
        if status.start_time is None:
            status.start_time = time.time()
        
        status.current_step = step_id
        status.steps[step_id] = StepStatus(
            step_id=step_id,
            tool=tool,
            status="running",
            start_time=time.time(),
        )
    
    def record_step_complete(
        self,
        task_id: str,
        step_id: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """记录步骤完成"""
        if task_id not in self._statuses:
            return
        
        status = self._statuses[task_id]
        if step_id in status.steps:
            step = status.steps[step_id]
            step.status = "completed" if success else "failed"
            step.end_time = time.time()
            step.error = error
            
            if success:
                status.completed_steps += 1
            else:
                status.failed_steps += 1
    
    def get_status(self, task_id: str) -> ExecutionStatus | None:
        """获取任务状态"""
        return self._statuses.get(task_id)
    
    def complete_task(self, task_id: str) -> None:
        """标记任务完成"""
        if task_id in self._statuses:
            self._statuses[task_id].end_time = time.time()
            self._statuses[task_id].current_step = None
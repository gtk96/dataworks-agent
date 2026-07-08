"""Orchestrator — 总指挥，负责目标分解、并行执行、结果汇总。

Loop Engineering 的核心组件：
- 用户设定目标
- Orchestrator 接手
- fan-out 并行执行
- 验收后 Ship 或重来
- 进度写进对话外的 Memory，循环自己续上

Validates: Requirements 39
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataworks_agent.governance.closed_loop_verifier import (
    ClosedLoopVerifier,
    VerificationResult,
)
from dataworks_agent.task_engine.task_chainer import TaskChainer
from dataworks_agent.task_engine.task_memory import (
    Decision,
    NextStep,
    TaskMemoryService,
)

logger = logging.getLogger(__name__)


class OrchestratorStatus(StrEnum):
    """Orchestrator 状态。"""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubTask:
    """子任务。"""

    task_id: str
    task_type: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class OrchestratorResult:
    """Orchestrator 执行结果。"""

    goal: str
    status: OrchestratorStatus
    sub_tasks: list[SubTask] = field(default_factory=list)
    verification: VerificationResult | None = None
    decisions: list[Decision] = field(default_factory=list)
    next_steps: list[NextStep] = field(default_factory=list)
    summary: str = ""


# 任务执行函数类型
TaskExecutor = Callable[[SubTask], Coroutine[Any, Any, dict[str, Any]]]


class Orchestrator:
    """Orchestrator — 总指挥。

    负责：
    1. 读取历史 Memory
    2. 分解目标为子任务
    3. 检查依赖关系
    4. 并行派发 (fan-out)
    5. 汇总结果
    6. 决定: Ship / Iterate
    7. 生成 next_steps (self-prompting)
    """

    def __init__(self) -> None:
        self._memory_service = TaskMemoryService()
        self._verifier = ClosedLoopVerifier()
        self._chainer = TaskChainer()
        self._executors: dict[str, TaskExecutor] = {}
        self._status = OrchestratorStatus.IDLE

    def register_executor(self, task_type: str, executor: TaskExecutor) -> None:
        """注册任务执行器。"""
        self._executors[task_type] = executor
        logger.info("注册任务执行器: %s", task_type)

    async def run(self, goal: str, context: dict[str, Any] | None = None) -> OrchestratorResult:
        """执行目标。

        Args:
            goal: 目标描述
            context: 上下文信息

        Returns:
            OrchestratorResult: 执行结果
        """
        self._status = OrchestratorStatus.RUNNING

        result = OrchestratorResult(
            goal=goal,
            status=OrchestratorStatus.RUNNING,
        )

        try:
            # 1. 分解目标为子任务
            sub_tasks = self._decompose_goal(goal, context or {})
            result.sub_tasks = sub_tasks

            # 2. 记录决策
            result.decisions.append(
                Decision(
                    decision=f"分解目标为 {len(sub_tasks)} 个子任务",
                    reason=f"目标: {goal}",
                    alternatives=["单任务顺序执行"],
                )
            )

            # 3. 并行执行子任务
            completed_tasks = await self._execute_parallel(sub_tasks)

            # 4. 汇总结果
            for task in completed_tasks:
                result.decisions.append(
                    Decision(
                        decision=f"子任务 {task.task_id} 完成",
                        reason=f"类型: {task.task_type}, 状态: {task.status.value}",
                    )
                )

            # 5. 验收检查
            all_passed = all(t.status == TaskStatus.COMPLETED for t in completed_tasks)

            if all_passed:
                # 6a. 全绿 → Ship
                result.status = OrchestratorStatus.COMPLETED
                result.summary = f"目标完成: {goal} ({len(completed_tasks)} 个子任务全部成功)"

                # 7. 生成 next_steps (self-prompting)
                result.next_steps = self._generate_next_steps(goal, completed_tasks)
            else:
                # 6b. 有红 → Iterate
                result.status = OrchestratorStatus.FAILED
                failed_tasks = [t for t in completed_tasks if t.status == TaskStatus.FAILED]
                result.summary = f"目标未完成: {goal} ({len(failed_tasks)} 个子任务失败)"

                # 记录失败原因
                for task in failed_tasks:
                    result.decisions.append(
                        Decision(
                            decision=f"子任务 {task.task_id} 失败",
                            reason=task.error,
                        )
                    )

        except Exception as e:
            logger.error("Orchestrator 执行异常: %s", e)
            result.status = OrchestratorStatus.FAILED
            result.summary = f"执行异常: {e}"

        self._status = result.status
        return result

    def _decompose_goal(self, goal: str, context: dict[str, Any]) -> list[SubTask]:
        """分解目标为子任务。

        这是一个简化的实现，实际应该由 LLM 来做目标分解。
        """
        sub_tasks: list[SubTask] = []

        # 根据上下文中的任务类型分解
        task_type = context.get("task_type", "DWD")

        if "ods" in goal.lower() or task_type == "ODS":
            sub_tasks.extend(
                [
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_node",
                        task_type="ods_node_create",
                        description="创建 ODS 节点",
                    ),
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_dml",
                        task_type="ods_dml_push",
                        description="推送 ODS DML",
                    ),
                ]
            )
        elif "dwd" in goal.lower() or task_type == "DWD":
            sub_tasks.extend(
                [
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_node",
                        task_type="dwd_node_create",
                        description="创建 DWD 节点",
                    ),
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_dml",
                        task_type="dwd_dml_push",
                        description="推送 DWD DML",
                    ),
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_deps",
                        task_type="dwd_dependency_config",
                        description="配置 DWD 依赖",
                    ),
                ]
            )
        elif "dim" in goal.lower() or task_type == "DIM":
            sub_tasks.extend(
                [
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_node",
                        task_type="dim_node_create",
                        description="创建 DIM 节点",
                    ),
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_dml",
                        task_type="dim_dml_push",
                        description="推送 DIM DML",
                    ),
                ]
            )
        elif "dws" in goal.lower() or task_type == "DWS":
            sub_tasks.extend(
                [
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_node",
                        task_type="dws_node_create",
                        description="创建 DWS 节点",
                    ),
                    SubTask(
                        task_id=f"sub_{task_type.lower()}_dml",
                        task_type="dws_dml_push",
                        description="推送 DWS DML",
                    ),
                ]
            )

        return sub_tasks

    async def _execute_parallel(self, sub_tasks: list[SubTask]) -> list[SubTask]:
        """并行执行子任务。

        fan-out 并行：多个 Agent 各干各的。
        """
        # 按依赖关系分组
        independent_tasks: list[SubTask] = []
        dependent_tasks: list[SubTask] = []

        for task in sub_tasks:
            if self._has_dependency(task, sub_tasks):
                dependent_tasks.append(task)
            else:
                independent_tasks.append(task)

        # 先执行独立任务
        if independent_tasks:
            await asyncio.gather(*[self._execute_task(task) for task in independent_tasks])

        # 再执行依赖任务
        for task in dependent_tasks:
            await self._execute_task(task)

        return sub_tasks

    async def _execute_task(self, task: SubTask) -> None:
        """执行单个子任务。"""
        task.status = TaskStatus.RUNNING

        executor = self._executors.get(task.task_type)
        if not executor:
            task.status = TaskStatus.FAILED
            task.error = f"未找到任务执行器: {task.task_type}"
            logger.warning("未找到任务执行器: %s", task.task_type)
            return

        try:
            result = await executor(task)
            task.result = result
            task.status = TaskStatus.COMPLETED
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error("子任务 %s 执行失败: %s", task.task_id, e)

    def _has_dependency(self, task: SubTask, all_tasks: list[SubTask]) -> bool:
        """检查任务是否有依赖。"""
        # 简化实现：DML 推送依赖节点创建，依赖配置依赖 DML 推送
        if "dml" in task.task_type:
            return any("node_create" in t.task_type for t in all_tasks)
        if "dependency" in task.task_type:
            return any("dml" in t.task_type for t in all_tasks)
        if "schedule" in task.task_type:
            return any("dependency" in t.task_type for t in all_tasks)
        return False

    def _generate_next_steps(self, goal: str, completed_tasks: list[SubTask]) -> list[NextStep]:
        """生成下一步建议 (self-prompting)。

        这是 Loop Engineering 的核心：
        上一轮跑完之后，不由人来想"下一步该问什么"，
        而是让系统根据已有进展，自己写下一轮要跑的 Prompt。
        """
        next_steps: list[NextStep] = []

        # 根据完成的任务类型生成下一步
        task_types = {t.task_type for t in completed_tasks}

        if any("node_create" in t for t in task_types):
            next_steps.append(
                NextStep(
                    step_type="verification",
                    description="运行闭环验收检查",
                    priority=1,
                )
            )

        if any("dml" in t for t in task_types):
            next_steps.append(
                NextStep(
                    step_type="schedule_config",
                    description="配置调度参数",
                    priority=2,
                )
            )

        if any("dependency" in t for t in task_types):
            next_steps.append(
                NextStep(
                    step_type="verification",
                    description="运行闭环验收检查",
                    priority=3,
                )
            )

        # 通用下一步
        next_steps.append(
            NextStep(
                step_type="ship",
                description="发布到生产环境",
                priority=99,
            )
        )

        return next_steps

    @property
    def status(self) -> OrchestratorStatus:
        """获取当前状态。"""
        return self._status

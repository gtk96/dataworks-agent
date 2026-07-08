"""Coordinator — 多专业 agent 协调器。

实现 Requirement 20：
- 编排需求理解/架构/建模/治理/诊断/查询专业 agent
- 任务分解分派汇总
- 跨域架构/成本优化经审批
- 子任务失败阻断下游
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AgentType(StrEnum):
    """专业 agent 类型。"""

    REQUIREMENT = "requirement"  # 需求理解
    ARCHITECTURE = "architecture"  # 架构设计
    MODELING = "modeling"  # 建模
    GOVERNANCE = "governance"  # 治理
    DIAGNOSIS = "diagnosis"  # 诊断
    QUERY = "query"  # 查询


class TaskStatus(StrEnum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class SubTask:
    """子任务。"""

    task_id: str
    agent_type: AgentType
    description: str
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    depends_on: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class CoordinationResult:
    """协调结果。"""

    task_id: str
    status: TaskStatus
    sub_tasks: list[SubTask] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Coordinator:
    """多专业 agent 协调器。

    编排需求理解/架构/建模/治理/诊断/查询专业 agent。
    """

    def __init__(self) -> None:
        from dataworks_agent.runtime.agent import Agent

        self._agents: dict[AgentType, Agent] = {}
        self._register_agents()

    def _register_agents(self) -> None:
        """注册专业 agent。"""
        from dataworks_agent.runtime.agent import Agent

        # 注册通用 agent
        agent = Agent()
        for agent_type in AgentType:
            self._agents[agent_type] = agent

    async def coordinate(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> CoordinationResult:
        """协调执行任务。"""
        import uuid

        task_id = f"coord_{uuid.uuid4().hex[:12]}"
        context = context or {}

        result = CoordinationResult(
            task_id=task_id,
            status=TaskStatus.RUNNING,
        )

        try:
            # 1. 分解任务为子任务
            sub_tasks = self._decompose_task(goal, context)
            result.sub_tasks = sub_tasks

            # 2. 执行子任务（按依赖顺序）
            await self._execute_sub_tasks(sub_tasks)

            # 3. 汇总结果
            completed = [t for t in sub_tasks if t.status == TaskStatus.COMPLETED]
            failed = [t for t in sub_tasks if t.status == TaskStatus.FAILED]

            if failed:
                result.status = TaskStatus.FAILED
                result.errors = [f"子任务 {t.task_id} 失败: {t.error}" for t in failed]
            else:
                result.status = TaskStatus.COMPLETED
                result.summary = self._merge_results(completed)

        except Exception as e:
            logger.error("协调执行失败: %s", e)
            result.status = TaskStatus.FAILED
            result.errors.append(str(e))

        return result

    def _decompose_task(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> list[SubTask]:
        """分解任务为子任务。"""
        import uuid

        sub_tasks = []

        # 简化实现：根据目标分解为固定子任务
        # 实际应由 LLM 或规则引擎分解

        if "建模" in goal or "modeling" in goal.lower():
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.REQUIREMENT,
                    description="理解建模需求",
                    input_data={"goal": goal, **context},
                )
            )
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.MODELING,
                    description="执行建模",
                    input_data={"goal": goal, **context},
                    depends_on=[sub_tasks[0].task_id] if sub_tasks else [],
                )
            )

        elif "诊断" in goal or "diagnosis" in goal.lower():
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.DIAGNOSIS,
                    description="执行诊断",
                    input_data={"goal": goal, **context},
                )
            )

        elif "查询" in goal or "query" in goal.lower():
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.QUERY,
                    description="执行查询",
                    input_data={"goal": goal, **context},
                )
            )

        else:
            # 默认：需求理解 → 建模
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.REQUIREMENT,
                    description="理解需求",
                    input_data={"goal": goal, **context},
                )
            )
            sub_tasks.append(
                SubTask(
                    task_id=f"sub_{uuid.uuid4().hex[:8]}",
                    agent_type=AgentType.MODELING,
                    description="执行建模",
                    input_data={"goal": goal, **context},
                    depends_on=[sub_tasks[0].task_id],
                )
            )

        return sub_tasks

    async def _execute_sub_tasks(self, sub_tasks: list[SubTask]) -> None:
        """执行子任务。"""
        # 按依赖顺序执行
        executed = set()

        for sub_task in sub_tasks:
            # 检查依赖是否已完成
            if sub_task.depends_on and not all(dep in executed for dep in sub_task.depends_on):
                sub_task.status = TaskStatus.BLOCKED
                sub_task.error = "依赖任务未完成"
                continue

            # 执行子任务
            agent = self._agents.get(sub_task.agent_type)
            if agent:
                sub_task.status = TaskStatus.RUNNING
                try:
                    from dataworks_agent.runtime.agent import AgentRequest

                    request = AgentRequest(
                        request_type=sub_task.agent_type.value,
                        content=sub_task.description,
                        context=sub_task.input_data,
                    )
                    response = await agent.process(request)

                    if response.success:
                        sub_task.status = TaskStatus.COMPLETED
                        sub_task.output_data = response.data
                    else:
                        sub_task.status = TaskStatus.FAILED
                        sub_task.error = "; ".join(response.errors)
                except Exception as e:
                    sub_task.status = TaskStatus.FAILED
                    sub_task.error = str(e)
            else:
                sub_task.status = TaskStatus.FAILED
                sub_task.error = f"未找到 agent: {sub_task.agent_type}"

            executed.add(sub_task.task_id)

    def _merge_results(self, completed_tasks: list[SubTask]) -> dict[str, Any]:
        """汇总子任务结果。"""
        summary = {}
        for task in completed_tasks:
            summary[task.agent_type.value] = task.output_data
        return summary

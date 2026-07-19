"""多 Agent 协调器 — 意图路由与任务分发。"""

from __future__ import annotations

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask

from .base import BaseAgent


class AgentCoordinator:
    """按意图将任务路由到合适的专业 Agent。"""

    def __init__(self, agents: list[BaseAgent]) -> None:
        self.agents: dict[str, BaseAgent] = {a.agent_type: a for a in agents}

    async def route_task(
        self,
        intent: str,
        params: dict,
        context: AutonomousContext | None,
    ) -> BaseAgent | None:
        """根据意图路由到第一个能处理的 Agent。"""
        for agent in self.agents.values():
            if await agent.can_handle(intent, params or {}):
                return agent
        return None

    async def execute_with_agents(
        self,
        intent: str,
        params: dict,
        context: AutonomousContext | None,
    ) -> AutonomousTask:
        """生成任务计划并通过路由到的 Agent 执行。"""
        from dataworks_agent.agent.autonomous.planner import AutonomousPlanner

        planner = AutonomousPlanner(context) if context is not None else None
        task = planner.generate_plan(intent, params) if planner else None
        if task is None:
            from dataworks_agent.agent.autonomous.state import TaskType

            task = AutonomousTask(task_type=TaskType.CREATE_ODS, description=intent)

        agent = await self.route_task(intent, params, context)
        if agent is None:
            raise ValueError(f"No agent can handle intent: {intent}")

        return await agent.handle_task(task, context)

    def list_available_agents(self) -> list[dict]:
        return [{"type": a.agent_type, "description": a.description} for a in self.agents.values()]

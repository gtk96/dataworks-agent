"""数仓建模 Agent — ODS / DWD / DIM / DWS / DMR 建表与建模任务。"""

from __future__ import annotations

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask

from .base import BaseAgent


class ModelingAgent(BaseAgent):
    agent_type = "modeling"
    description = "数仓建模 Agent"

    keywords = ["建表", "建模", "create table", "ods", "dwd", "dim", "dws", "dmr"]

    async def can_handle(self, intent: str, params: dict) -> bool:
        return any(kw in intent.lower() for kw in self.keywords)

    async def handle_task(
        self, task: AutonomousTask, context: AutonomousContext | None
    ) -> AutonomousTask:
        from dataworks_agent.agent.autonomous.executor import AutonomousExecutor

        executor = AutonomousExecutor(None, None)
        await executor.execute_task(task)
        return task

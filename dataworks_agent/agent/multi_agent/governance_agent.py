"""数仓治理 Agent — 词根校验、命名规范、DDL 检查。"""

from __future__ import annotations

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask

from .base import BaseAgent


class GovernanceAgent(BaseAgent):
    agent_type = "governance"
    description = "数仓治理 Agent"

    keywords = ["治理", "词根", "规范", "命名", "governance", "校验", "ddl 检查"]

    async def can_handle(self, intent: str, params: dict) -> bool:
        return any(kw in intent.lower() for kw in self.keywords)

    async def handle_task(
        self, task: AutonomousTask, context: AutonomousContext | None
    ) -> AutonomousTask:
        # 治理 Agent 的完整实现依赖治理规则引擎，当前阶段先标记为已接收。
        return task

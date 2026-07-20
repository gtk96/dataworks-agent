"""智能问数 Agent — 自然语言查询指标与数据。"""

from __future__ import annotations

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask

from .base import BaseAgent


class QueryAgent(BaseAgent):
    agent_type = "query"
    description = "智能问数 Agent"

    keywords = ["查询", "指标", "GMV", "订单量", "ask_data", "query", "看数据", "统计"]

    async def can_handle(self, intent: str, params: dict) -> bool:
        return any(kw in intent.lower() for kw in self.keywords)

    async def handle_task(
        self, task: AutonomousTask, context: AutonomousContext | None
    ) -> AutonomousTask:
        # 问数 Agent 的完整实现依赖语义层与查询引擎，当前阶段先标记为已接收。
        return task

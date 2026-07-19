"""异常排查 Agent — 任务失败诊断、血缘分析。"""

from __future__ import annotations

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask

from .base import BaseAgent


class DiagnosisAgent(BaseAgent):
    agent_type = "diagnosis"
    description = "异常排查 Agent"

    keywords = ["诊断", "排查", "失败", "异常", "diagnose", "报错", "为什么失败"]

    async def can_handle(self, intent: str, params: dict) -> bool:
        return any(kw in intent.lower() for kw in self.keywords)

    async def handle_task(
        self, task: AutonomousTask, context: AutonomousContext | None
    ) -> AutonomousTask:
        # 诊断 Agent 的完整实现依赖下游服务，当前阶段先标记为已接收。
        return task

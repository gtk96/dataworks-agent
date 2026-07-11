"""Agent 核心模块 - 对话式数仓操作

提供简化的对话接口，包装现有的 runtime.agent.Agent。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.executor.task_executor import ExecutionResult, TaskExecutor
from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.agent.planner.task_planner import TaskPlanner

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    """对话响应"""

    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ChatAgent:
    """对话式数仓操作 Agent

    提供简化的 chat() 接口，内部委托给 runtime.agent.Agent。
    """

    def __init__(self) -> None:
        from dataworks_agent.runtime.agent import Agent, AgentRequest

        self._agent = Agent()
        self._AgentRequest = AgentRequest
        self._intent_parser = IntentParser()
        self._task_planner = TaskPlanner()
        self._task_executor = TaskExecutor()

    async def chat(self, message: str, request_type: str | None = None) -> ChatResponse:
        """处理用户消息

        Args:
            message: 用户输入
            request_type: 请求类型 (query/modeling/clarification)，默认从 NLU 解析
        """
        if not message or not message.strip():
            return ChatResponse(
                message="请输入您的需求",
                success=False,
                error="empty message",
            )

        try:
            # 1. 意图解析
            intent = self._intent_parser.parse(message)
            logger.info(
                "NLU 解析: action=%s, confidence=%.2f",
                intent.action,
                intent.confidence,
            )

            # 2. 任务规划
            plan = self._task_planner.plan(intent)
            logger.info(
                "任务计划: task_id=%s, 步骤数=%d",
                plan.task_id,
                len(plan.steps),
            )

            # 3. 任务执行
            result = self._task_executor.execute(plan)

            # 4. 构建响应
            return self._build_response(intent, plan, result)
        except Exception as e:
            logger.error("ChatAgent 处理失败: %s", e)
            return ChatResponse(
                message=f"处理失败: {e}",
                success=False,
                error=str(e),
            )

    def _build_response(
        self,
        intent: Any,
        plan: Any,
        result: ExecutionResult,
    ) -> ChatResponse:
        """构建响应"""
        if result.success:
            message = self._format_success_message(intent, result)
            return ChatResponse(
                message=message,
                success=True,
                data={
                    "task_id": result.task_id,
                    "steps_completed": len(result.step_results),
                },
            )
        else:
            message = self._format_error_message(intent, result)
            return ChatResponse(
                message=message,
                success=False,
                error=result.errors[0] if result.errors else "未知错误",
            )

    def _format_success_message(self, intent: Any, result: ExecutionResult) -> str:
        """格式化成功消息"""
        action_messages = {
            "create_table": "已成功创建表",
            "query_lineage": "血缘查询结果",
            "check_status": "任务状态",
        }
        prefix = action_messages.get(intent.action, "操作已完成")
        table_name = intent.params.get("table_name", "")
        return f"{prefix} {table_name}" if table_name else prefix

    def _format_error_message(self, intent: Any, result: ExecutionResult) -> str:
        """格式化错误消息"""
        return f"操作失败: {'; '.join(result.errors)}"

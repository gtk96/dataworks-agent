"""Agent 核心模块 - 对话式数仓操作

提供简化的对话接口，包装现有的 runtime.agent.Agent。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import IntentParser

logger = logging.getLogger(__name__)

# 意图到请求类型的映射
INTENT_TO_REQUEST_TYPE: dict[str, str] = {
    "create_table": "modeling",
    "query_lineage": "query",
    "check_status": "query",
    "unknown": "query",
}


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
            # 如果未指定 request_type，使用 NLU 解析
            if request_type is None:
                intent = self._intent_parser.parse(message)
                request_type = INTENT_TO_REQUEST_TYPE.get(intent.action, "query")
                logger.info(
                    "NLU 解析: action=%s, confidence=%.2f, request_type=%s",
                    intent.action,
                    intent.confidence,
                    request_type,
                )

            request = self._AgentRequest(
                request_type=request_type,
                content=message.strip(),
            )
            response = await self._agent.process(request)

            return ChatResponse(
                message=response.content or "处理完成",
                success=response.success,
                data=response.data if isinstance(response.data, dict) else {},
                error=response.errors[0] if response.errors else None,
            )
        except Exception as e:
            logger.error("ChatAgent 处理失败: %s", e)
            return ChatResponse(
                message=f"处理失败: {e}",
                success=False,
                error=str(e),
            )

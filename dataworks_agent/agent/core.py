"""Agent 核心模块 - 对话式数仓操作

提供简化的对话接口，包装现有的 runtime.agent.Agent。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

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

    async def chat(self, message: str, request_type: str = "query") -> ChatResponse:
        """处理用户消息

        Args:
            message: 用户输入
            request_type: 请求类型 (query/modeling/clarification)，默认 "query"
        """
        if not message or not message.strip():
            return ChatResponse(
                message="请输入您的需求",
                success=False,
                error="empty message",
            )

        try:
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

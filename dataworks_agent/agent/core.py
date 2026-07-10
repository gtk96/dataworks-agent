"""Agent 核心模块 - 对话式数仓操作"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    """Agent 响应"""
    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Agent:
    """数仓操作 Agent"""

    def __init__(self):
        self._initialized = True

    def chat(self, message: str) -> AgentResponse:
        """处理用户消息"""
        return AgentResponse(
            message=f"收到您的消息: {message}",
            success=True,
        )

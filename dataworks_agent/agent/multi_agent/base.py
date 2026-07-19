"""Agent 基类与协议定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dataworks_agent.agent.autonomous.state import AutonomousContext, AutonomousTask


class BaseAgent(ABC):
    """所有专业 Agent 必须实现的接口。"""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Agent 唯一类型标识，如 ``"modeling"``。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """面向用户的简短能力描述。"""

    @abstractmethod
    async def can_handle(self, intent: str, params: dict) -> bool:
        """判断当前 Agent 是否能处理该意图。

        默认实现为纯字符串关键词匹配，子类可覆写以接入更复杂的 NLU。
        """
        raise NotImplementedError

    @abstractmethod
    async def handle_task(
        self, task: AutonomousTask, context: AutonomousContext | None
    ) -> AutonomousTask:
        """执行任务并返回更新后的任务对象。"""
        raise NotImplementedError

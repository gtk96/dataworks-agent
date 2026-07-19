"""Registry and guarded execution for conversational Agent tools."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from dataworks_agent.agent.tools.base import AgentTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools: Iterable[AgentTool]) -> None:
        items = list(tools)
        self._tools = {tool.name: tool for tool in items}
        if len(self._tools) != len(items):
            raise ValueError("tool names must be unique")

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.failure(
                f"未知工具：{name}",
                error_code="unknown_tool",
            )
        try:
            result = await tool.execute(dict(arguments), context)
        except Exception as exc:
            logger.exception("Agent tool %s failed", name)
            result = ToolResult.failure(
                f"工具 {name} 执行失败：{exc}",
                error_code="tool_exception",
                recoverable=not tool.side_effect.can_write,
            )
        return result.for_effect(tool.side_effect)

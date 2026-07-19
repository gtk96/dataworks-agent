"""Typed Agent tool contracts and failure policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from dataworks_agent.agent.tools.base import SideEffect, ToolContext, ToolResult
from dataworks_agent.agent.tools.registry import ToolRegistry


@dataclass
class FakeTool:
    name: str
    side_effect: SideEffect
    result: ToolResult | None = None
    error: Exception | None = None

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if self.error is not None:
            raise self.error
        assert context.conversation_id
        assert isinstance(arguments, dict)
        assert self.result is not None
        return self.result


@pytest.mark.asyncio
async def test_read_tool_failure_is_recoverable() -> None:
    tool = FakeTool(
        name="read_probe",
        side_effect=SideEffect.READ,
        result=ToolResult.failure("offline", error_code="dependency_unavailable"),
    )

    result = await ToolRegistry([tool]).execute(
        tool.name,
        {},
        ToolContext(conversation_id="conv-read", state={}),
    )

    assert result.success is False
    assert result.recoverable is True
    assert result.uncertain_write is False
    assert result.error_code == "dependency_unavailable"


@pytest.mark.asyncio
async def test_read_tool_exception_is_recoverable() -> None:
    tool = FakeTool(
        name="read_probe",
        side_effect=SideEffect.READ,
        error=RuntimeError("transport failed"),
    )

    result = await ToolRegistry([tool]).execute(
        tool.name,
        {},
        ToolContext(conversation_id="conv-read", state={}),
    )

    assert result.success is False
    assert result.error_code == "tool_exception"
    assert result.recoverable is True
    assert result.uncertain_write is False


def test_write_is_uncertain_only_after_boundary() -> None:
    before = ToolResult.failure("validation", write_boundary_crossed=False).for_effect(
        SideEffect.DEV_WRITE
    )
    after = ToolResult.failure("timeout", write_boundary_crossed=True).for_effect(
        SideEffect.DEV_WRITE
    )

    assert before.uncertain_write is False
    assert after.uncertain_write is True
    assert after.recoverable is False


@pytest.mark.asyncio
async def test_registry_rejects_unknown_tool_without_uncertain_write() -> None:
    result = await ToolRegistry([]).execute(
        "missing",
        {},
        ToolContext(conversation_id="conv-missing", state={}),
    )

    assert result.success is False
    assert result.error_code == "unknown_tool"
    assert result.uncertain_write is False


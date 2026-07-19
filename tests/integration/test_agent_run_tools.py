"""Typed Agent tool contracts and failure policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.context.metadata_provider import MetadataQueryResult
from dataworks_agent.agent.tools.base import SideEffect, ToolContext, ToolResult
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool


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


@pytest.mark.asyncio
async def test_find_table_returns_candidates_without_llm() -> None:
    provider = AsyncMock()
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[
            {
                "full_name": "dw.dwd_orders",
                "layer": "dwd",
                "comment": "订单明细",
                "album_name": "订单域",
            }
        ],
    )

    result = await TableDiscoveryTool(provider).execute(
        {"keyword": "找订单表"},
        ToolContext(conversation_id="conv-find", state={"state_version": 2}),
    )

    interaction = result.data["interaction"]
    assert result.success is True
    assert interaction["purpose"] == "select_table"
    assert interaction["state_version"] == 3
    assert interaction["options"][0]["payload"]["params"]["table_name"] == "dw.dwd_orders"
    assert interaction["options"][0]["payload"]["selected_resources"]["table"] == "dw.dwd_orders"
    provider.search_table.assert_awaited_once_with("订单", "找订单表")


@pytest.mark.asyncio
async def test_find_table_no_hit_is_recoverable() -> None:
    provider = AsyncMock()
    provider.search_table.return_value = None

    result = await TableDiscoveryTool(provider).execute(
        {"keyword": "订单"},
        ToolContext(conversation_id="conv-find", state={"state_version": 4}),
    )

    assert result.success is False
    assert result.recoverable is True
    assert result.uncertain_write is False
    assert result.error_code == "table_not_found"
    assert result.data["interaction"]["type"] == "free_text"
    assert result.data["interaction"]["state_version"] == 5


@pytest.mark.asyncio
async def test_find_table_groups_large_candidate_set_by_layer() -> None:
    provider = AsyncMock()
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[
            {"full_name": f"dw.{layer}_orders_{index}", "layer": layer}
            for index, layer in enumerate(["dwd"] * 6 + ["ods"] * 4)
        ],
    )

    result = await TableDiscoveryTool(provider).execute(
        {"keyword": "订单"},
        ToolContext(conversation_id="conv-find", state={}),
    )

    interaction = result.data["interaction"]
    assert interaction["purpose"] == "select_layer"
    assert [option["id"] for option in interaction["options"]] == ["layer_dwd", "layer_ods"]
    assert interaction["options"][0]["payload"]["params"] == {
        "keyword": "订单",
        "layer": "dwd",
        "tool_name": "find_table",
    }

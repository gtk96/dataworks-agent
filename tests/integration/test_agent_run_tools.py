"""Typed Agent tool contracts and failure policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.table_discovery_service import (
    DiscoveryResult,
    DiscoveryStatus,
    TableDiscoveryService,
)
from dataworks_agent.agent.tools.base import SideEffect, ToolContext, ToolResult
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool
from dataworks_agent.api_clients.provider_errors import ProviderAuthenticationError


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
    service = AsyncMock()
    service.search.return_value = DiscoveryResult(
        status=DiscoveryStatus.FOUND,
        provider="cookie_bff",
        candidates=[
            {
                "full_name": "dw.dwd_orders",
                "layer": "dwd",
                "comment": "订单明细",
                "album_name": "订单域",
            }
        ],
    )

    result = await TableDiscoveryTool(service=service).execute(
        {"keyword": "找订单表"},
        ToolContext(conversation_id="conv-find", state={"state_version": 2}),
    )

    interaction = result.data["interaction"]
    assert result.success is True
    assert interaction["purpose"] == "select_table"
    assert interaction["state_version"] == 3
    assert interaction["options"][0]["payload"]["params"]["table_name"] == "dw.dwd_orders"
    assert interaction["options"][0]["payload"]["selected_resources"]["table"] == "dw.dwd_orders"
    service.search.assert_awaited_once_with("订单", "找订单表")


@pytest.mark.asyncio
async def test_find_table_authenticated_no_hit_waits_for_user_without_error() -> None:
    service = AsyncMock()
    service.search.return_value = DiscoveryResult(
        status=DiscoveryStatus.NOT_FOUND,
        provider="cookie_bff",
    )

    result = await TableDiscoveryTool(service=service).execute(
        {"keyword": "订单"},
        ToolContext(conversation_id="conv-find", state={"state_version": 4}),
    )

    assert result.success is True
    assert result.recoverable is True
    assert result.uncertain_write is False
    assert result.error_code == ""
    assert result.data["agent_mode"] == "waiting_user"
    assert result.data["interaction"]["type"] == "free_text"
    assert result.data["interaction"]["state_version"] == 5


@pytest.mark.asyncio
async def test_find_table_groups_large_candidate_set_by_layer() -> None:
    service = AsyncMock()
    service.search.return_value = DiscoveryResult(
        status=DiscoveryStatus.FOUND,
        provider="cookie_bff",
        candidates=[
            {"full_name": f"dw.{layer}_orders_{index}", "layer": layer}
            for index, layer in enumerate(["dwd"] * 6 + ["ods"] * 4)
        ],
    )

    result = await TableDiscoveryTool(service=service).execute(
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


@pytest.mark.asyncio
async def test_bare_identifier_uses_maxcompute_exact_match_before_bff() -> None:
    provider = AsyncMock()
    maxcompute = AsyncMock()
    maxcompute.table_exists.side_effect = [True, False]
    service = TableDiscoveryService(
        metadata_provider=provider,
        maxcompute=maxcompute,
        projects=["giikin_dev", "giikin"],
    )

    result = await service.search("dwd_order_info", "dwd_order_info")

    assert result.status is DiscoveryStatus.FOUND
    assert result.candidates[0]["full_name"] == "giikin_dev.dwd_order_info"
    provider.search_table.assert_not_awaited()


@pytest.mark.asyncio
async def test_chinese_search_preserves_auth_required() -> None:
    provider = AsyncMock()
    provider.search_table.side_effect = ProviderAuthenticationError(
        "cookie_auth_required",
        "USER_NOT_LOGGED_IN",
        provider="cookie_bff",
    )
    service = TableDiscoveryService(metadata_provider=provider, projects=[])

    result = await service.search("订单域", "订单域")

    assert result.status is DiscoveryStatus.AUTH_REQUIRED
    assert result.error_code == "cookie_auth_required"


@pytest.mark.asyncio
async def test_find_table_auth_failure_is_recoverable_not_not_found() -> None:
    service = AsyncMock()
    service.search.return_value = DiscoveryResult(
        status=DiscoveryStatus.AUTH_REQUIRED,
        provider="cookie_bff",
        error_code="cookie_auth_required",
    )

    result = await TableDiscoveryTool(service=service).execute(
        {"keyword": "订单域"},
        ToolContext(conversation_id="conv-auth", state={"state_version": 1}),
    )

    assert result.success is False
    assert result.error_code == "table_search_auth_required"
    assert result.data["agent_mode"] == "recoverable_error"
    assert "没有找到" not in result.message
    assert result.uncertain_write is False

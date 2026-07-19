"""Observed Agent capability health coverage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.capabilities import CapabilityRegistry


class OfflineCDP:
    async def test_connection(self) -> bool:
        return False


class BrokenBFF:
    async def _refresh_csrf(self) -> None:
        raise RuntimeError("cookie decrypt failed")


@pytest.mark.asyncio
async def test_instantiated_but_unreachable_clients_are_reported_offline() -> None:
    state = SimpleNamespace(
        _bff_client=BrokenBFF(),
        _cdp_client=OfflineCDP(),
        _openapi_client=None,
        _maxcompute_client=None,
        _node_client=None,
        _official_mcp_client=None,
    )
    config = SimpleNamespace(
        aliyun_access_key_id="",
        aliyun_access_key_secret="",
        llm_api_key="configured",
        llm_model="missing-model",
        llm_base_url="https://example.invalid/v1",
    )
    llm_probe = AsyncMock(side_effect=RuntimeError("503 model_not_found"))

    snapshot = await CapabilityRegistry(
        state=state,
        settings_obj=config,
        llm_probe=llm_probe,
        ttl_seconds=15,
    ).snapshot()

    assert snapshot["cdp_9222"].configured is True
    assert snapshot["cdp_9222"].online is False
    assert snapshot["cookie_bff"].online is False
    assert snapshot["table_search"].online is False
    assert snapshot["ida_query"].online is False
    assert snapshot["llm"].online is False
    assert "model_not_found" in snapshot["llm"].status


@pytest.mark.asyncio
async def test_snapshot_is_cached_and_derived_capabilities_share_bff_probe() -> None:
    bff = SimpleNamespace(_refresh_csrf=AsyncMock(return_value=None))
    state = SimpleNamespace(
        _bff_client=bff,
        _cdp_client=None,
        _openapi_client=None,
        _maxcompute_client=None,
        _node_client=None,
        _official_mcp_client=None,
    )
    config = SimpleNamespace(
        aliyun_access_key_id="",
        aliyun_access_key_secret="",
        llm_api_key="",
        llm_model="",
        llm_base_url="",
    )
    registry = CapabilityRegistry(state=state, settings_obj=config, ttl_seconds=15)

    first = await registry.snapshot()
    second = await registry.snapshot()

    assert first["cookie_bff"].online is True
    assert first["table_search"].online is True
    assert first["ida_query"].online is True
    assert second["cookie_bff"].checked_at == first["cookie_bff"].checked_at
    bff._refresh_csrf.assert_awaited_once()

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.api_clients.openapi_node_adapter import OpenAPINodeAdapter
from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence


@pytest.mark.asyncio
async def test_advertisement_report_dwd_requires_positive_directory_evidence() -> None:
    from dataworks_agent.modeling.node_placement import NodePlacementPolicy, NodePlacementRequest

    expected = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"

    async def reader(path: str) -> ExistingDirectoryEvidence:
        return ExistingDirectoryEvidence.from_check(
            path, "datastudio_directory_tree", path == expected
        )

    decision = await NodePlacementPolicy().resolve(
        NodePlacementRequest(
            environment="test",
            layer="DWD",
            business_domain="106_广告报告",
        ),
        reader,
    )

    assert decision.status == "resolved"
    assert decision.selected_path == expected
    assert decision.creates_directory is False


@pytest.mark.asyncio
async def test_advertisement_report_dim_blocks_without_confirmed_directory() -> None:
    from dataworks_agent.modeling.node_placement import NodePlacementPolicy, NodePlacementRequest

    async def reader(path: str) -> ExistingDirectoryEvidence:
        return ExistingDirectoryEvidence.from_check(path, "datastudio_directory_tree", False)

    decision = await NodePlacementPolicy().resolve(
        NodePlacementRequest("test", "DIM", "106_广告报告"),
        reader,
    )

    assert decision.status == "blocked"
    assert decision.selected_path == ""
    assert "01_DIM" in decision.reason


@pytest.mark.asyncio
async def test_production_resolves_only_unique_confirmed_candidate() -> None:
    from dataworks_agent.modeling.node_placement import NodePlacementPolicy, NodePlacementRequest

    candidates = ("业务流程/A/02_DWD", "业务流程/B/02_DWD")

    async def reader(path: str) -> ExistingDirectoryEvidence:
        return ExistingDirectoryEvidence.from_check(
            path, "datastudio_directory_tree", path == candidates[1]
        )

    decision = await NodePlacementPolicy().resolve(
        NodePlacementRequest(
            environment="production",
            layer="DWD",
            business_domain="orders",
            candidate_paths=candidates,
        ),
        reader,
    )

    assert decision.status == "resolved"
    assert decision.selected_path == candidates[1]


@pytest.mark.asyncio
async def test_production_multiple_confirmed_candidates_need_context() -> None:
    from dataworks_agent.modeling.node_placement import NodePlacementPolicy, NodePlacementRequest

    candidates = ("业务流程/A/02_DWD", "业务流程/B/02_DWD")

    async def reader(path: str) -> ExistingDirectoryEvidence:
        return ExistingDirectoryEvidence.from_check(path, "datastudio_directory_tree", True)

    decision = await NodePlacementPolicy().resolve(
        NodePlacementRequest(
            environment="production",
            layer="DWD",
            business_domain="orders",
            candidate_paths=candidates,
        ),
        reader,
    )

    assert decision.status == "needs_context"
    assert decision.candidates == candidates
    assert decision.selected_path == ""


@pytest.mark.asyncio
async def test_production_missing_evidence_blocks_without_default_path() -> None:
    from dataworks_agent.modeling.node_placement import NodePlacementPolicy, NodePlacementRequest

    async def reader(path: str) -> ExistingDirectoryEvidence:
        return ExistingDirectoryEvidence.from_check(path, "no_positive_evidence", False)

    decision = await NodePlacementPolicy().resolve(
        NodePlacementRequest(
            environment="production",
            layer="DWD",
            business_domain="orders",
            candidate_paths=("业务流程/A/02_DWD",),
        ),
        reader,
    )

    assert decision.status == "blocked"
    assert decision.selected_path == ""
    assert decision.creates_directory is False


@pytest.mark.asyncio
async def test_adapter_rejects_absent_mismatched_or_stale_evidence() -> None:
    api = AsyncMock()
    api.list_nodes.return_value = {"PagingInfo": {"Nodes": [], "TotalCount": 0}}
    adapter = OpenAPINodeAdapter(api)
    path = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD/test_node"

    assert await adapter.create_node("test_node", path) is None
    mismatch = ExistingDirectoryEvidence.from_check("业务流程/其他", "datastudio_directory_tree", True)
    assert await adapter.create_node("test_node", path, directory_evidence=mismatch) is None
    stale = ExistingDirectoryEvidence(
        path="业务流程/106_广告报告/MaxCompute/数据开发/02_DWD",
        source="datastudio_directory_tree",
        checked_at=(datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        confirmed=True,
    )
    assert await adapter.create_node("test_node", path, directory_evidence=stale) is None
    api.create_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_uses_valid_evidence_and_never_creates_container() -> None:
    api = AsyncMock()
    api.list_nodes.return_value = {"PagingInfo": {"Nodes": [], "TotalCount": 0}}
    api.create_node.return_value = {"Id": "node-1"}
    adapter = OpenAPINodeAdapter(api)
    parent = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"
    evidence = ExistingDirectoryEvidence.from_check(parent, "datastudio_directory_tree", True)

    node_id = await adapter.create_node(
        "test_node",
        f"{parent}/test_node",
        directory_evidence=evidence,
    )

    assert node_id == "node-1"
    api.create_node.assert_awaited_once()
    assert api.create_node.await_args.kwargs["container_id"] is None
    assert api.create_node.await_args.kwargs["scene"] == "DATAWORKS_PROJECT"

"""Governance lineage export pure function tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.governance.lineage_export import build_preview, prune_excluded
from dataworks_agent.governance.lineage_models import (
    DependencyEdge,
    LineageNode,
    RootNode,
    TraversalResult,
)


def _sample_result() -> TraversalResult:
    nodes = {
        "1": LineageNode(node_id="1", table_name="dwd_a", layer="DWD", depth=0),
        "2": LineageNode(node_id="2", table_name="ods_b", layer="ODS", depth=1),
        "3": LineageNode(node_id="3", table_name="ods_c", layer="ODS", depth=1),
    }
    edges = [
        DependencyEdge(parent_node_id="2", child_node_id="1"),
        DependencyEdge(parent_node_id="3", child_node_id="1"),
    ]
    return TraversalResult(nodes=nodes, edges=edges, reached_limit=False)


class TestBuildPreview:
    def test_preview_shape(self) -> None:
        root = RootNode(node_id="1", table_name="dwd_a")
        preview = build_preview(root, _sample_result())
        assert preview["root_table"] == "dwd_a"
        assert preview["summary"]["node_total"] == 3
        assert len(preview["dependencies"]) == 2


class TestPruneExcluded:
    def test_prune_removes_excluded_branch(self) -> None:
        result = _sample_result()
        pruned = prune_excluded(result, "1", {"3"})
        assert "3" not in pruned.nodes
        assert len(pruned.edges) == 1

    def test_empty_excluded_returns_same(self) -> None:
        result = _sample_result()
        assert prune_excluded(result, "1", set()) is result


class TestCollectConcurrent:
    """v16 F6-7：collect_nodes_concurrent 并发 + 信号量限流行为级断言。"""

    @pytest.mark.asyncio
    async def test_concurrent_calls_bff_get_node_code(self) -> None:
        """N 个节点应并发触发 bff.get_node_code（并行而非串行）。"""
        import asyncio
        import time

        from dataworks_agent.governance.lineage_models import LineageNode
        from dataworks_agent.governance.lineage_service import collect_nodes_concurrent

        # mock bff：每次 get_node_code sleep 100ms（async def 必须 await）
        async def fake_code(node_id, env="prod"):
            await asyncio.sleep(0.1)
            return {"content": f"code for {node_id}"}

        bff = MagicMock()
        bff.get_node_code = AsyncMock(side_effect=fake_code)

        nodes = {
            str(i): LineageNode(node_id=str(i), table_name=f"ods_{i}", layer="ODS", depth=1)
            for i in range(8)
        }

        start = time.monotonic()
        result = await collect_nodes_concurrent(bff, nodes, "prod", concurrency=8)
        elapsed = time.monotonic() - start

        assert len(result) == 8
        # 8 个并发：100ms / 8 ≈ 0.0125s；串行会 ≈ 0.8s
        # 阈值取 0.3s 留余量
        assert elapsed < 0.3, f"并发失败，elapsed={elapsed:.3f}s"
        assert bff.get_node_code.await_count == 8

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self) -> None:
        """concurrency=2 + 6 节点应至少 3 批（每批 ≤ 2）。"""
        import asyncio

        from dataworks_agent.governance.lineage_models import LineageNode
        from dataworks_agent.governance.lineage_service import collect_nodes_concurrent

        # 记录每次进入 sem 的瞬时并发数
        active = 0
        peak = 0

        async def fake_get_node_code(node_id, env="prod"):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {"content": "x"}

        bff = MagicMock()
        bff.get_node_code = AsyncMock(side_effect=fake_get_node_code)

        nodes = {
            str(i): LineageNode(node_id=str(i), table_name=f"ods_{i}", layer="ODS", depth=1)
            for i in range(6)
        }
        await collect_nodes_concurrent(bff, nodes, "prod", concurrency=2)

        assert peak <= 2, f"信号量未生效，peak={peak}"
        assert peak >= 1

    @pytest.mark.asyncio
    async def test_per_node_failure_does_not_break_others(self) -> None:
        """部分节点失败不应影响其他节点（行为兼容旧 collect_node）。"""

        from dataworks_agent.governance.lineage_models import LineageNode
        from dataworks_agent.governance.lineage_service import collect_nodes_concurrent

        async def flaky(node_id, env="prod"):
            if int(node_id) % 2 == 0:
                raise RuntimeError("mock bff failure")
            return {"content": f"ok {node_id}"}

        bff = MagicMock()
        bff.get_node_code = AsyncMock(side_effect=flaky)

        nodes = {
            str(i): LineageNode(node_id=str(i), table_name=f"ods_{i}", layer="ODS", depth=1)
            for i in range(4)
        }
        result = await collect_nodes_concurrent(bff, nodes, "prod", concurrency=4)

        assert len(result) == 4
        error_count = sum(1 for c in result if c.node.status == "error")
        ok_count = sum(1 for c in result if c.node.status != "error")
        assert error_count == 2
        assert ok_count == 2

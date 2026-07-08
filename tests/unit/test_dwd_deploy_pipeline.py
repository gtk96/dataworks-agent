"""DwdDeployPipeline AK/SK 路径单测（Task 8a/8b）。

验证：建表走 MaxCompute(execute_ddl 且 DROP 被剥离)、节点操作走 node 适配器、
依赖内嵌 update_vertex 的 dependencies；publish=False 时跳过发布。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from dataworks_agent.modeling.dwd.deploy import DwdDeployPipeline

STRUCTURED = {
    "sources": [{"table_name": "ods_test", "alias": "t1", "is_master": True}],
    "targets": [
        {
            "table_name": "dwd_test_day",
            "fields": [
                {"name": "id", "type": "STRING", "comment": "主键"},
                {"name": "dt", "type": "STRING", "comment": "分区"},
            ],
            "partition_fields": ["dt"],
            "logical_primary_keys": ["id"],
        }
    ],
    "field_mappings": [{"source_field_name": "id", "target_field_name": "id"}],
}


@dataclass
class _DDLResult:
    success: bool
    instance_id: str = "inst_1"
    error: str | None = None


class FakeMC:
    def __init__(self, exists: bool = False, ok: bool = True) -> None:
        self._exists = exists
        self._ok = ok
        self.executed_ddl: list[str] = []
        self.exist_calls: list[tuple[str, str]] = []

    async def table_exists(self, table, *, project=None):
        self.exist_calls.append((table, project))
        return self._exists

    async def execute_ddl(self, sql):
        self.executed_ddl.append(sql)
        return _DDLResult(success=self._ok, error=None if self._ok else "boom")


class FakeNodes:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []
        self.updated: list[tuple[str, str]] = []
        self.vertex: list[tuple[str, dict]] = []
        self.deployed: list[list[str]] = []
        self.last_error: str | None = None

    async def create_node(self, name, path, language="odps-sql"):
        self.created.append((name, path, language))
        return "NODE_1"

    async def update_node(self, uuid, content):
        self.updated.append((uuid, content))
        return True

    async def update_vertex(self, uuid, config, instance_mode="Immediately"):
        self.vertex.append((uuid, config))
        return True

    async def deploy_nodes(self, uuids, comment=""):
        self.deployed.append(list(uuids))
        return True


@pytest.fixture
def nodes():
    return FakeNodes()


class TestDeployAkSkPath:
    async def test_creates_table_via_mc_with_drop_stripped(self, nodes):
        mc = FakeMC(exists=False, ok=True)
        pipeline = DwdDeployPipeline(bff_client=None, node_client=nodes, mc_client=mc)
        result = await pipeline.deploy(STRUCTURED, mc_project="dataworks_dev", publish=False)

        assert result["success"] is True
        assert result["steps"]["execute_create_table"]["status"] == "ok"
        # DDL 执行过一次，且开头的 drop table 已被剥离，只剩 create
        assert len(mc.executed_ddl) == 1
        ddl = mc.executed_ddl[0].lower()
        assert "drop table" not in ddl
        assert "create table" in ddl

    async def test_skips_create_when_table_exists(self, nodes):
        mc = FakeMC(exists=True)
        pipeline = DwdDeployPipeline(bff_client=None, node_client=nodes, mc_client=mc)
        result = await pipeline.deploy(STRUCTURED, mc_project="dataworks_dev", publish=False)
        assert result["steps"]["execute_create_table"]["status"] == "skipped"
        assert mc.executed_ddl == []

    async def test_node_ops_go_through_adapter_with_deps_inline(self, nodes):
        mc = FakeMC(exists=False, ok=True)
        pipeline = DwdDeployPipeline(bff_client=None, node_client=nodes, mc_client=mc)
        result = await pipeline.deploy(STRUCTURED, mc_project="dataworks_dev", publish=False)

        assert nodes.created and nodes.created[0][0] == "dwd_test_day"
        assert nodes.updated and nodes.updated[0][0] == "NODE_1"
        # 适配器路径：依赖内嵌 update_vertex 的 dependencies
        assert nodes.vertex
        _, cfg = nodes.vertex[0]
        assert "dependencies" in cfg
        assert result["steps"]["publish"]["status"] == "skipped"

    async def test_publish_calls_deploy(self, nodes):
        mc = FakeMC(exists=False, ok=True)
        pipeline = DwdDeployPipeline(bff_client=None, node_client=nodes, mc_client=mc)
        await pipeline.deploy(STRUCTURED, mc_project="dataworks_dev", publish=True)
        assert nodes.deployed == [["NODE_1"]]

    async def test_create_table_failure_stops(self, nodes):
        mc = FakeMC(exists=False, ok=False)
        pipeline = DwdDeployPipeline(bff_client=None, node_client=nodes, mc_client=mc)
        result = await pipeline.deploy(STRUCTURED, mc_project="dataworks_dev", publish=False)
        assert result["success"] is False
        assert result["steps"]["execute_create_table"]["status"] == "failed"
        # 建表失败即中止，不应建节点
        assert nodes.created == []

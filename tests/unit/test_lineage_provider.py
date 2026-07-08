"""OpenAPILineageProvider 单元测试（Task 8c）— 按真机响应结构映射。"""

from __future__ import annotations

import json

import pytest

from dataworks_agent.governance.lineage_provider import (
    OpenAPILineageProvider,
    _script_content_from_spec,
)


class _Body:
    def __init__(self, m):
        self._m = m

    def to_map(self):
        return self._m


class _FakeClient:
    def __init__(self):
        self.node_pages: list[list[dict]] = []
        self.deps: dict[str, list[dict]] = {}
        self.node_specs: dict[str, str | None] = {}
        self.raise_deps_for: set[str] = set()

    async def list_nodes(self, *, page_number=1, page_size=100, container_id=None, scene=None):
        idx = page_number - 1
        batch = self.node_pages[idx] if idx < len(self.node_pages) else []
        return _Body({"PagingInfo": {"Nodes": batch}})

    async def list_node_dependencies(self, node_id, *, page_number=1, page_size=100):
        if str(node_id) in self.raise_deps_for:
            raise RuntimeError("boom")
        return _Body({"PagingInfo": {"Nodes": self.deps.get(str(node_id), [])}})

    async def get_node(self, node_id):
        return _Body({"Node": {"Id": node_id, "Spec": self.node_specs.get(str(node_id))}})


def _provider(client) -> OpenAPILineageProvider:
    return OpenAPILineageProvider(client, mc_project="dataworks", page_size=2, max_pages=5)


def _node(id_, name, outputs=None):
    outs = [{"Data": d} for d in (outputs or [])]
    return {"Id": id_, "Name": name, "Outputs": {"NodeOutputs": outs}}


@pytest.fixture
def client():
    return _FakeClient()


class TestUpstreamTasks:
    async def test_match_by_name(self, client):
        client.node_pages = [[_node("100", "dwd_mkt_ad_group_day")]]
        tasks = await _provider(client).get_upstream_tasks("odps.dataworks.dwd_mkt_ad_group_day")
        assert tasks == [{"id": "100", "name": "dwd_mkt_ad_group_day"}]

    async def test_match_by_output_table(self, client):
        client.node_pages = [[_node("200", "some_node", outputs=["dataworks.dwd_x"])]]
        tasks = await _provider(client).get_upstream_tasks("odps.dataworks.dwd_x")
        assert tasks[0]["id"] == "200"

    async def test_not_found(self, client):
        client.node_pages = [[_node("1", "other")]]
        assert await _provider(client).get_upstream_tasks("odps.dataworks.missing") == []


class TestPagination:
    async def test_stops_on_partial_page(self, client):
        # page_size=2；首页只 1 条 → 停止，不请求第二页
        client.node_pages = [[_node("1", "a")], [_node("2", "b")]]
        nodes = await _provider(client)._iter_all_nodes()
        assert [n["Id"] for n in nodes] == ["1"]

    async def test_full_then_partial(self, client):
        client.node_pages = [[_node("1", "a"), _node("2", "b")], [_node("3", "c")]]
        nodes = await _provider(client)._iter_all_nodes()
        assert [n["Id"] for n in nodes] == ["1", "2", "3"]

    async def test_max_pages_cap(self, client):
        # 全是满页，max_pages=5 * page_size=2 → 最多 10 条
        client.node_pages = [[_node(str(i), f"n{i}"), _node(f"{i}b", f"n{i}b")] for i in range(10)]
        prov = OpenAPILineageProvider(client, mc_project="dataworks", page_size=2, max_pages=5)
        nodes = await prov._iter_all_nodes()
        assert len(nodes) == 10


class TestNodeList:
    async def test_filter_by_substring(self, client):
        client.node_pages = [[_node("1", "dwd_mkt_ad"), _node("2", "dws_fin")]]
        results = await _provider(client).get_node_list(search="mkt")
        assert results == [{"id": "1", "name": "dwd_mkt_ad"}]


class TestParents:
    async def test_returns_id_name(self, client):
        client.deps["500"] = [_node("500", "self"), _node("400", "dwd_parent")]
        parents = await _provider(client).get_node_parents_by_depth(node_id=500)
        assert {"id": "400", "name": "dwd_parent"} in parents
        assert {"id": "500", "name": "self"} in parents

    async def test_returns_none_on_error(self, client):
        client.raise_deps_for = {"999"}
        assert await _provider(client).get_node_parents_by_depth(node_id=999) is None


class TestNodeCode:
    async def test_parses_script_content(self, client):
        spec = {
            "version": "1.1.0",
            "kind": "CycleWorkflow",
            "spec": {"nodes": [{"script": {"content": "insert overwrite table t select 1"}}]},
        }
        client.node_specs["7"] = json.dumps(spec)
        code = await _provider(client).get_node_code(7)
        assert code == {"content": "insert overwrite table t select 1"}

    async def test_empty_when_no_spec(self, client):
        client.node_specs["7"] = None
        assert await _provider(client).get_node_code(7) == {}

    async def test_empty_when_bad_spec(self, client):
        client.node_specs["7"] = "{not json"
        assert await _provider(client).get_node_code(7) == {}


class TestScriptContentHelper:
    def test_none_input(self):
        assert _script_content_from_spec(None) is None

    def test_first_node_with_content(self):
        spec = json.dumps({"spec": {"nodes": [{"script": {}}, {"script": {"content": "x"}}]}})
        assert _script_content_from_spec(spec) == "x"

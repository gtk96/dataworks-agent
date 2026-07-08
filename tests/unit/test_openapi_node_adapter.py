"""OpenAPINodeAdapter 单元测试（mock OpenAPI client）— Task 8b。

覆盖：create_node(flowspec 一次成型)、update_node/update_vertex(get-modify-write)、
deploy_nodes、get_node_uuid_by_path(分页扫描匹配 Script.Path)、错误经 last_error。
"""

from __future__ import annotations

import json

import pytest

from dataworks_agent.api_clients.openapi_client import OpenAPIError
from dataworks_agent.api_clients.openapi_node_adapter import OpenAPINodeAdapter


class FakeAPI:
    """可编排的假 OpenAPI client。"""

    def __init__(self) -> None:
        self.created_specs: list[str] = []
        self.updated: list[tuple[str, str]] = []
        self.deployments: list[list[str]] = []
        self._node_spec: dict | None = None
        self._create_error: OpenAPIError | None = None
        self._list_pages: list[list[dict]] = []
        self._list_total = 0

    async def create_node(self, *, spec, container_id, scene):
        if self._create_error:
            raise self._create_error
        self.created_specs.append(spec)
        assert container_id is None
        assert scene == "DATAWORKS_PROJECT"
        return {"Id": "NODE_NEW"}

    async def get_node(self, node_id):
        return {"Node": {"Spec": json.dumps(self._node_spec)}}

    async def update_node(self, *, node_id, spec):
        self.updated.append((node_id, spec))
        return {"ok": True}

    async def create_deployment(self, *, object_ids, description):
        self.deployments.append(object_ids)
        return {"Id": "DEP_1"}

    async def list_nodes(self, *, page_number, page_size, scene):
        idx = page_number - 1
        nodes = self._list_pages[idx] if idx < len(self._list_pages) else []
        return {"PagingInfo": {"Nodes": nodes, "TotalCount": self._list_total}}


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture
def adapter(api):
    return OpenAPINodeAdapter(api, project="dataworks")


class TestCreateNode:
    async def test_create_returns_id_and_builds_flowspec(self, adapter, api):
        uuid = await adapter.create_node("dwd_x", "业务流程/DWD/dwd_x", language="odps-sql")
        assert uuid == "NODE_NEW"
        spec = json.loads(api.created_specs[0])
        node = spec["spec"]["nodes"][0]
        assert node["script"]["path"] == "业务流程/DWD/dwd_x"
        assert node["outputs"]["nodeOutputs"][0]["data"] == "dataworks.dwd_x"

    async def test_create_error_sets_last_error(self, adapter, api):
        api._create_error = OpenAPIError("Forbidden", "no perm")
        uuid = await adapter.create_node("x", "p/x")
        assert uuid is None
        assert "Forbidden" in adapter.last_error

    async def test_create_bad_language(self, adapter):
        assert await adapter.create_node("x", "p/x", language="weird") is None
        assert "language" in adapter.last_error


class TestUpdateNode:
    async def test_update_content_writes_into_spec(self, adapter, api):
        api._node_spec = {
            "version": "1.1.0",
            "kind": "CycleWorkflow",
            "spec": {"nodes": [{"id": "n1", "script": {"content": "old"}}]},
        }
        ok = await adapter.update_node("n1", "SELECT 2;")
        assert ok is True
        _, spec_str = api.updated[0]
        assert json.loads(spec_str)["spec"]["nodes"][0]["script"]["content"] == "SELECT 2;"


class TestUpdateVertex:
    async def test_trigger_params_deps_merged(self, adapter, api):
        api._node_spec = {
            "version": "1.1.0",
            "kind": "CycleWorkflow",
            "spec": {
                "nodes": [
                    {
                        "id": "n1",
                        "name": "dwd_x",
                        "script": {"content": "c"},
                        "trigger": {"cron": "old"},
                        "outputs": {
                            "nodeOutputs": [{"data": "dataworks.dwd_x", "isDefault": True}]
                        },
                    }
                ]
            },
        }
        ok = await adapter.update_vertex(
            "n1",
            {
                "trigger": {"cron": "00 00 07 * * ?", "cycleType": "Daily"},
                "script": {
                    "parameters": [
                        {"name": "bizdate", "type": "System", "value": "${workspace.bizdate}"}
                    ]
                },
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
            },
        )
        assert ok is True
        spec = json.loads(api.updated[0][1])
        node = spec["spec"]["nodes"][0]
        assert node["trigger"]["cron"] == "00 00 07 * * ?"
        assert node["script"]["parameters"][0]["name"] == "bizdate"
        assert node["script"]["parameters"][0]["artifactType"] == "Variable"
        depends = spec["spec"]["flow"][0]["depends"]
        assert depends[0]["type"] == "CrossCycleDependsOnSelf"
        assert depends[0]["output"] == "dataworks.dwd_x"

    async def test_outputs_merged_into_spec(self, adapter, api):
        api._node_spec = {"spec": {"nodes": [{"id": "n1", "name": "t", "outputs": {}}]}}
        outs = {"nodeOutputs": [{"data": "n1", "refTableName": "t", "isDefault": True}]}
        await adapter.update_vertex("n1", {"outputs": outs})
        spec = json.loads(api.updated[0][1])
        assert spec["spec"]["nodes"][0]["outputs"] == outs

    async def test_normal_dependency_uses_manual_sourcetype(self, adapter, api):
        api._node_spec = {
            "spec": {"nodes": [{"id": "n1", "name": "dwd_x", "outputs": {"nodeOutputs": []}}]}
        }
        await adapter.update_vertex(
            "n1", {"dependencies": [{"type": "Normal", "output": "dataworks.ods_y"}]}
        )
        spec = json.loads(api.updated[0][1])
        dep = spec["spec"]["flow"][0]["depends"][0]
        assert dep == {
            "type": "Normal",
            "sourceType": "Manual",
            "output": "dataworks.ods_y",
            "refTableName": "dataworks.ods_y",
        }


class TestDeployNodes:
    async def test_deploy_calls_create_deployment(self, adapter, api):
        ok = await adapter.deploy_nodes(["n1", "n2"], comment="c")
        assert ok is True
        assert api.deployments[0] == ["n1", "n2"]


class TestGetNodeUuidByPath:
    async def test_match_on_second_page(self, adapter, api):
        api._list_total = 150
        api._list_pages = [
            [{"Id": "1", "Script": {"Path": "a/x"}}],
            [{"Id": "42", "Script": {"Path": "业务流程/DWD/dwd_x"}}],
        ]
        uuid = await adapter.get_node_uuid_by_path("业务流程/DWD/dwd_x")
        assert uuid == "42"

    async def test_no_match_returns_none(self, adapter, api):
        api._list_total = 1
        api._list_pages = [[{"Id": "1", "Script": {"Path": "a/x"}}]]
        assert await adapter.get_node_uuid_by_path("nope/here") is None

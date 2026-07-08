"""create_di_node 双路径单测（Task 8b DI 接线）。

适配器(无 _post)：走 create_node(language="di") + update_node + update_vertex(内嵌 dependencies)。
bff(有 _post)：走 ide/createPackage + update_node + update_vertex + _put addNodeDependencies。
"""

from __future__ import annotations

import json

from dataworks_agent.services.ods_di.create_node import create_di_node

DI_CONFIG = {"type": "job", "version": "2.0", "steps": []}


class FakeAdapter:
    """AK/SK 适配器：无 _post/_put。"""

    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.updated: list[tuple] = []
        self.vertex: list[tuple] = []
        self.last_error = None

    async def create_node(self, name, path, language="odps-sql"):
        self.created.append((name, path, language))
        return "DI_NODE_1"

    async def update_node(self, uuid, content):
        self.updated.append((uuid, content))
        return True

    async def update_vertex(self, uuid, config, instance_mode="Immediately"):
        self.vertex.append((uuid, config))
        return True


class FakeBff:
    """bff：有 _post/_put。"""

    project_id = 0

    def __init__(self) -> None:
        self.posts: list[tuple] = []
        self.puts: list[tuple] = []
        self.updated: list[tuple] = []
        self.vertex: list[tuple] = []
        self.last_error = None

    async def _post(self, ep, payload):
        self.posts.append((ep, payload))
        return {"data": {"uuid": "BFF_NODE_1"}}

    async def _put(self, ep, payload):
        self.puts.append((ep, payload))
        return {"code": 200}

    async def update_node(self, uuid, content):
        self.updated.append((uuid, content))
        return True

    async def update_vertex(self, uuid, config, instance_mode="Immediately"):
        self.vertex.append((uuid, config))
        return True


async def test_adapter_path_builds_di_node():
    ad = FakeAdapter()
    res = await create_di_node(
        ad,
        node_name="ods_x_hour",
        node_path="业务流程/x/ods_x_hour",
        di_config=DI_CONFIG,
        cron="00 30 06 * * ?",
        cycle_type="Daily",
        parameters=[],
        schedule=True,
    )
    assert res["status"] == "created"
    assert res["uuid"] == "DI_NODE_1"
    # 用 language=di 建节点
    assert ad.created[0][2] == "di"
    # 写入的是 DataX json content
    assert json.loads(ad.updated[0][1]) == DI_CONFIG
    # 依赖内嵌 update_vertex
    assert "dependencies" in ad.vertex[0][1]


async def test_bff_path_uses_createpackage_and_addnodedeps():
    bff = FakeBff()
    res = await create_di_node(
        bff,
        node_name="ods_x_hour",
        node_path="业务流程/x/ods_x_hour",
        di_config=DI_CONFIG,
        cron="00 30 06 * * ?",
        cycle_type="Daily",
        parameters=[],
        schedule=True,
    )
    assert res["uuid"] == "BFF_NODE_1"
    # 走 createPackage（runtime DI）
    assert bff.posts[0][0] == "ide/createPackage"
    assert bff.posts[0][1]["script"]["runtime"]["command"] == "DI"
    # 依赖走独立 _put addNodeDependencies
    assert bff.puts[0][0] == "ide/addNodeDependencies"


async def test_create_failure_returns_error():
    ad = FakeAdapter()

    async def _fail(name, path, language="odps-sql"):
        ad.last_error = "no perm"
        return None

    ad.create_node = _fail
    res = await create_di_node(
        ad, node_name="x", node_path="p/x", di_config=DI_CONFIG, schedule=False
    )
    assert res["status"] == "failed"
    assert res["error"] == "no perm"

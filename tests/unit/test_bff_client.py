"""DataWorks BFF 客户端 — payload 构造单元测试。

不连真实 BFF,直接给 DataWorksClient._http 注入 FakeAsyncClient,断言请求 URL/方法/payload。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dataworks_agent.api_clients.bff_client import DataWorksClient


class FakeAsyncClient:
    """httpx.AsyncClient 替身: 拦截 put/get/post,记录最后一次调用,返回受控响应。"""

    is_closed = False  # DataWorksClient._client() 每次调用都会检查 is_closed

    def __init__(self) -> None:
        self.last_url: str = ""
        self.last_params: dict = {}
        self.last_json: dict = {}
        self.last_method: str = ""
        self.response_json: dict = {"code": 200, "data": "ok"}

    def set_response(self, payload: dict) -> None:
        self.response_json = payload

    async def _capture(self, method: str, url: str, **kwargs):
        self.last_method = method
        self.last_url = url
        self.last_params = kwargs.get("params", {})
        self.last_json = kwargs.get("json", {})
        resp = MagicMock()
        resp.json.return_value = self.response_json
        resp.raise_for_status = MagicMock()
        return resp

    async def put(self, url: str, **kwargs):
        return await self._capture("PUT", url, **kwargs)

    async def get(self, url: str, **kwargs):
        return await self._capture("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self._capture("POST", url, **kwargs)

    async def aclose(self):
        self.is_closed = True


@pytest.fixture
def client() -> DataWorksClient:
    c = DataWorksClient()
    c.project_id = "12345"
    c.tenant_id = "67890"
    return c


@pytest.mark.asyncio
async def test_update_node_sends_correct_payload(client: DataWorksClient):
    fake = FakeAsyncClient()
    client._http = fake
    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        ok = await client.update_node("uuid-abc", "SELECT 1")

    assert ok is True
    assert fake.last_method == "PUT"
    assert fake.last_url.endswith("/ide/updateNode")
    assert fake.last_json["projectId"] == "12345"
    assert fake.last_json["uuid"] == "uuid-abc"
    assert fake.last_json["script"]["content"] == "SELECT 1"


@pytest.mark.asyncio
async def test_update_vertex_includes_trigger_and_params(client: DataWorksClient):
    fake = FakeAsyncClient()
    client._http = fake
    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        ok = await client.update_vertex(
            "uuid-xyz",
            {
                "trigger": {"type": "Scheduler", "cron": "00 00 06 * * ?", "cycleType": "Daily"},
                "script": {
                    "parameters": [
                        {"name": "bizdate", "type": "System", "value": "${workspace.bizdate}"}
                    ]
                },
                "strategy": {"instanceMode": "Immediately"},
                "outputs": {
                    "nodeOutputs": [
                        {"data": "uuid-xyz", "refTableName": "t", "artifactType": "NodeOutput"}
                    ]
                },
            },
        )

    assert ok is True
    assert fake.last_method == "POST"
    assert fake.last_url.endswith("/ide/updateVertex")
    assert fake.last_json["projectId"] == "12345"
    assert fake.last_json["uuid"] == "uuid-xyz"
    assert fake.last_json["instanceMode"] == "Immediately"
    assert fake.last_json["trigger"]["cron"] == "00 00 06 * * ?"
    assert fake.last_json["script"]["parameters"][0]["name"] == "bizdate"
    assert fake.last_json["outputs"]["nodeOutputs"][0]["refTableName"] == "t"


@pytest.mark.asyncio
async def test_update_vertex_omits_absent_keys(client: DataWorksClient):
    """只传 trigger,不应包含 outputs/script。"""
    fake = FakeAsyncClient()
    client._http = fake
    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        await client.update_vertex("uuid-1", {"trigger": {"type": "Scheduler"}})

    assert "trigger" in fake.last_json
    assert "outputs" not in fake.last_json
    assert "script" not in fake.last_json


@pytest.mark.asyncio
async def test_get_upstream_tasks_parses_response(client: DataWorksClient):
    """BFF 响应 data 字段直接是任务 list。"""
    fake_tasks = [
        {"taskId": 1, "taskName": "t1", "outputTable": "ods_xxx"},
        {"taskId": 2, "taskName": "t2", "outputTable": "ods_yyy"},
    ]
    fake = FakeAsyncClient()
    fake.set_response({"code": 200, "data": fake_tasks})
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        tasks = await client.get_upstream_tasks("odps.dataworks.dim_xxx")
    assert len(tasks) == 2
    assert tasks[0]["outputTable"] == "ods_xxx"
    assert tasks[1]["taskId"] == 2
    assert fake.last_url.endswith("/dma/getTableUpstreamTasks")
    assert fake.last_params["entityGuid"] == "odps.dataworks.dim_xxx"


@pytest.mark.asyncio
async def test_get_upstream_tasks_returns_empty_on_non_200(client: DataWorksClient):
    """BFF 响应非 200 时返回空列表。"""
    fake = FakeAsyncClient()
    fake.set_response({"code": 500, "message": "fail"})
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        tasks = await client.get_upstream_tasks("odps.dataworks.dim_xxx")
    assert tasks == []


@pytest.mark.asyncio
async def test_list_lineage_returns_data_block(client: DataWorksClient):
    fake_data = {"inOutputDag": {"edges": []}, "nodes": []}
    fake = FakeAsyncClient()
    fake.set_response({"code": 200, "data": fake_data})
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        data = await client.list_lineage("odps.dataworks.dim_xxx")
    assert data == fake_data
    assert fake.last_url.endswith("/dma/listLineage")
    assert fake.last_params["entityType"] == "odps-table"


@pytest.mark.asyncio
async def test_update_node_returns_false_on_non_200(client: DataWorksClient):
    fake = FakeAsyncClient()
    fake.set_response({"code": 500, "message": "server error"})
    client._http = fake
    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        ok = await client.update_node("uuid", "SELECT 1")
    assert ok is False

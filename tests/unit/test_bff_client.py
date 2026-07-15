"""DataWorks BFF 客户端 — payload 构造单元测试。

不连真实 BFF,直接给 DataWorksClient._http 注入 FakeAsyncClient,断言请求 URL/方法/payload。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence


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


@pytest.mark.asyncio
async def test_list_meta_albums_maps_paged_data(client: DataWorksClient):
    fake = FakeAsyncClient()
    fake.set_response(
        {
            "code": 200,
            "data": {
                "data": [
                    {"id": 436, "albumName": "orders", "tableCount": 39},
                    {"id": 505, "albumName": "family", "tableCount": 12},
                ]
            },
        }
    )
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        albums = await client.list_meta_albums()

    assert [item["id"] for item in albums] == [436, 505]
    assert fake.last_url.endswith("/dma/list")
    assert fake.last_params["scene"] == "all"


@pytest.mark.asyncio
async def test_list_meta_album_entities_flattens_nested_entity(client: DataWorksClient):
    fake = FakeAsyncClient()
    fake.set_response(
        {
            "code": 200,
            "data": {
                "data": [
                    {
                        "albumId": 436,
                        "relationId": 9,
                        "categoryId": 7,
                        "remark": "manual business note",
                        "entity": {
                            "entityGuid": "odps.giikin.tb_dws_order",
                            "name": "tb_dws_order",
                            "databaseName": "giikin",
                            "ownerName": "owner",
                            "comment": "order summary",
                            "entityType": "odps-table",
                            "qualifiedName": "maxcompute-table.giikin.tb_dws_order",
                        },
                    }
                ]
            },
        }
    )
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        entities = await client.list_meta_album_entities(436)

    assert entities == [
        {
            "album_id": 436,
            "relation_id": 9,
            "category_id": 7,
            "remark": "manual business note",
            "project": "giikin",
            "table_name": "tb_dws_order",
            "comment": "order summary",
            "entity_guid": "odps.giikin.tb_dws_order",
            "qualified_name": "maxcompute-table.giikin.tb_dws_order",
            "entity_type": "odps-table",
            "owner": "owner",
        }
    ]
    assert fake.last_url.endswith("/dma/listAlbumEntity")
    assert fake.last_params["entityType"] == "odps-table"


@pytest.mark.asyncio
async def test_meta_album_read_methods_return_empty_on_non_200(client: DataWorksClient):
    fake = FakeAsyncClient()
    fake.set_response({"code": 500, "message": "failed"})
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        assert await client.list_meta_albums() == []
        assert await client.list_meta_album_categories(436) == []
        assert await client.list_meta_album_entities(436) == []
        assert await client.get_meta_album_wiki(436) is None


@pytest.mark.asyncio
async def test_get_meta_album_wiki_returns_none_for_null_data(client: DataWorksClient):
    fake = FakeAsyncClient()
    fake.set_response({"code": 200, "data": None})
    client._http = fake

    with patch("dataworks_agent.api_clients.bff_client.decrypt_cookie", return_value="mock_cookie"):
        wiki = await client.get_meta_album_wiki(505)

    assert wiki is None


def test_reset_auth_cache_discards_cached_credentials(client: DataWorksClient):
    client._cookie = "stale-cookie"
    client._csrf_token = "stale-token"
    client._csrf_time = 123.0
    client.last_error = "expired"

    client.reset_auth_cache()

    assert client._cookie == ""
    assert client._csrf_token == ""
    assert client._csrf_time == 0
    assert client.last_error is None


@pytest.mark.asyncio
async def test_create_node_reuses_exact_existing_path_without_create_package(
    client: DataWorksClient,
):
    client.get_node_uuid_by_path = AsyncMock(return_value="existing-uuid")
    client._post = AsyncMock()

    result = await client.create_node("node", "????/00_ODS/node")

    assert result == "existing-uuid"
    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_node_refuses_missing_parent_without_create_package(client: DataWorksClient):
    client.get_node_uuid_by_path = AsyncMock(return_value=None)
    client.check_existing_directory = AsyncMock(
        return_value=ExistingDirectoryEvidence.from_check(
            "????/00_ODS", "no_positive_evidence", False
        )
    )
    client._post = AsyncMock()

    result = await client.create_node("node", "????/00_ODS/node")

    assert result is None
    assert "??" in client.last_error
    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_node_creates_node_when_parent_is_confirmed_without_folder_creation(
    client: DataWorksClient,
):
    client.get_node_uuid_by_path = AsyncMock(return_value=None)
    client.check_existing_directory = AsyncMock(
        return_value=ExistingDirectoryEvidence.from_check(
            "business/00_ODS", "node_path_prefix", True
        )
    )
    client._post = AsyncMock(return_value={"code": 200, "data": {"uuid": "new-uuid"}})

    result = await client.create_node("node", "business/00_ODS/node")

    assert result == "new-uuid"
    client.check_existing_directory.assert_awaited_once_with("business/00_ODS")
    client._post.assert_awaited_once()
    endpoint, payload = client._post.await_args.args
    assert endpoint == "ide/createPackage"
    assert payload["kind"] == "Node"
    assert payload["name"] == "node"
    assert payload["script"]["path"] == "business/00_ODS/node"

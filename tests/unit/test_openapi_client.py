"""OpenAPI_Client 单元测试（mock SDK）— Requirement 3, 5。

覆盖：AK/SK 配置、节点域方法请求字段、指数退避重试、错误分类。
"""

from __future__ import annotations

import pytest
from Tea.exceptions import TeaException

from dataworks_agent.api_clients import openapi_client as oc_mod
from dataworks_agent.api_clients.openapi_client import (
    DataWorksOpenAPIClient,
    OpenAPIError,
    _is_retryable,
)
from dataworks_agent.auth import AliyunCredentials


class _FakeResp:
    def __init__(self, body):
        self.body = body


@pytest.fixture
def fake_sdk(monkeypatch):
    """把 openapi_client.Client 换成可编排的假 SDK 客户端。"""
    holder: dict = {}

    class FakeClient:
        def __init__(self, config):
            holder["config"] = config
            holder["client"] = self
            self.invocations: list[tuple[str, object]] = []
            self.script: dict[str, list] = {}

        def _make(self, name):
            async def _fn(request):
                self.invocations.append((name, request))
                outcomes = self.script.get(name)
                if outcomes:
                    o = outcomes.pop(0)
                    if isinstance(o, Exception):
                        raise o
                    return o
                return _FakeResp({"ok": True})

            return _fn

        def __getattr__(self, name):
            if name.endswith("_async"):
                return object.__getattribute__(self, "_make")(name)
            raise AttributeError(name)

    monkeypatch.setattr(oc_mod, "Client", FakeClient)

    # 避免真实退避睡眠拖慢测试
    async def _no_sleep(_):
        return None

    monkeypatch.setattr(oc_mod.asyncio, "sleep", _no_sleep)
    return holder


@pytest.fixture
def creds():
    return AliyunCredentials(access_key_id="LTAI_id", access_key_secret="secret_1234")


def _make_client(creds, **kw) -> DataWorksOpenAPIClient:
    return DataWorksOpenAPIClient(
        creds=creds,
        region="cn-shenzhen",
        endpoint="dataworks.cn-shenzhen.aliyuncs.com",
        project_id=0,
        base_delay=0.0,
        **kw,
    )


def _throttle() -> TeaException:
    return TeaException({"code": "Throttling.Api", "message": "qps", "data": {"statusCode": 429}})


class TestConfig:
    def test_config_uses_akssk(self, creds, fake_sdk):
        client = _make_client(creds)
        client._ensure_client()
        cfg = fake_sdk["config"]
        assert cfg.access_key_id == "LTAI_id"
        assert cfg.access_key_secret == "secret_1234"
        assert cfg.region_id == "cn-shenzhen"
        assert cfg.endpoint == "dataworks.cn-shenzhen.aliyuncs.com"

    def test_client_cached(self, creds, fake_sdk):
        client = _make_client(creds)
        assert client._ensure_client() is client._ensure_client()


class TestNodeDomain:
    async def test_get_node_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.get_node("node_1")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "get_node_async"
        assert req.id == "node_1"
        assert req.project_id == 0

    async def test_list_nodes_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_nodes(container_id="c1", page_size=50, scene="DATAWORKS_PROJECT")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_nodes_async"
        assert req.container_id == "c1"
        assert req.page_size == 50
        assert req.scene == "DATAWORKS_PROJECT"
        assert req.project_id == 0

    async def test_create_node_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.create_node(spec='{"spec":1}', container_id="wf1", scene="s")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "create_node_async"
        assert req.spec == '{"spec":1}'
        assert req.container_id == "wf1"

    async def test_update_node_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.update_node(node_id="n9", spec='{"s":2}')
        name, req = fake_sdk["client"].invocations[0]
        assert name == "update_node_async"
        assert req.id == "n9"
        assert req.spec == '{"s":2}'

    async def test_returns_body(self, creds, fake_sdk):
        client = _make_client(creds)
        client._ensure_client()
        fake_sdk["client"].script["get_node_async"] = [_FakeResp({"node": "x"})]
        body = await client.get_node("n1")
        assert body == {"node": "x"}


class TestMetadataLineageDomain:
    async def test_get_table_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.get_table("tbl_guid_1", include_business_metadata=True)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "get_table_async"
        assert req.id == "tbl_guid_1"
        assert req.include_business_metadata is True

    async def test_list_tables_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_tables(name="dwd_mkt", page_size=20)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_tables_async"
        assert req.name == "dwd_mkt"
        assert req.page_size == 20

    async def test_list_catalogs_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_catalogs(name="dataworks", page_size=20)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_catalogs_async"
        assert req.name == "dataworks"
        assert req.page_size == 20

    async def test_list_databases_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_databases(parent_meta_entity_id="cat_1")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_databases_async"
        assert req.parent_meta_entity_id == "cat_1"

    async def test_list_schemas_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_schemas(parent_meta_entity_id="db_1", types="ODPS")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_schemas_async"
        assert req.parent_meta_entity_id == "db_1"
        assert req.types == "ODPS"

    async def test_list_columns_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_columns("tbl_guid_1", name="id")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_columns_async"
        assert req.table_id == "tbl_guid_1"
        assert req.name == "id"

    async def test_list_lineages_upstream(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_lineages(dst_entity_name="dataworks.dwd_x", need_attach_relationship=True)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_lineages_async"
        assert req.dst_entity_name == "dataworks.dwd_x"
        assert req.need_attach_relationship is True
        assert req.src_entity_name is None

    async def test_list_lineages_downstream(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_lineages(src_entity_name="dataworks.ods_x")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_lineages_async"
        assert req.src_entity_name == "dataworks.ods_x"

    async def test_metadata_methods_retry_on_throttle(self, creds, fake_sdk):
        client = _make_client(creds, max_retry=3)
        client._ensure_client()
        fake_sdk["client"].script["list_tables_async"] = [_throttle(), _FakeResp({"ok": 1})]
        body = await client.list_tables(name="x")
        assert body == {"ok": 1}
        assert len(fake_sdk["client"].invocations) == 2


class TestDeploymentDomain:
    async def test_create_deployment_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.create_deployment(object_ids=["n1", "n2"], description="deploy dwd_x")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "create_deployment_async"
        assert req.object_ids == ["n1", "n2"]
        assert req.type == "Online"
        assert req.description == "deploy dwd_x"
        assert req.project_id == 0

    async def test_get_deployment_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.get_deployment("dep_1")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "get_deployment_async"
        assert req.id == "dep_1"

    async def test_exec_deployment_stage_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.exec_deployment_stage(deployment_id="dep_1", code="stage_a")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "exec_deployment_stage_async"
        assert req.id == "dep_1"
        assert req.code == "stage_a"


class TestDataSourceDomain:
    async def test_list_data_sources_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_data_sources(name="dataworks", types="odps", page_size=50)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_data_sources_async"
        assert req.name == "dataworks"
        assert req.types == "odps"
        assert req.page_size == 50
        assert req.project_id == 0

    async def test_get_data_source_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.get_data_source("ds_1")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "get_data_source_async"
        assert req.id == "ds_1"


class TestDIDomain:
    async def test_create_dijob_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.create_dijob(
            job_name="di_sync_x",
            source_data_source_type="mysql",
            destination_data_source_type="odps",
            migration_type="FullAndIncremental",
            table_mappings=[{"src": "a", "dst": "b"}],
        )
        name, req = fake_sdk["client"].invocations[0]
        assert name == "create_dijob_async"
        assert req.job_name == "di_sync_x"
        assert req.source_data_source_type == "mysql"
        assert req.destination_data_source_type == "odps"
        assert req.migration_type == "FullAndIncremental"
        assert req.project_id == 0

    async def test_get_dijob_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.get_dijob("dij_1", with_details=True)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "get_dijob_async"
        assert req.dijob_id == "dij_1"
        assert req.with_details is True

    async def test_start_dijob_force_rerun(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.start_dijob("dij_1", force_to_rerun=True)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "start_dijob_async"
        assert req.dijob_id == "dij_1"
        assert req.force_to_rerun is True

    async def test_stop_dijob_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.stop_dijob("dij_1", instance_id="inst_9")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "stop_dijob_async"
        assert req.dijob_id == "dij_1"
        assert req.instance_id == "inst_9"


class TestDataQualityDomain:
    async def test_list_evaluation_tasks_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_data_quality_evaluation_tasks(table_guid="g1", page_size=20)
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_data_quality_evaluation_tasks_async"
        assert req.table_guid == "g1"
        assert req.page_size == 20
        assert req.project_id == 0

    async def test_list_rules_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_data_quality_rules(data_quality_evaluation_task_id="t1")
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_data_quality_rules_async"
        assert req.data_quality_evaluation_task_id == "t1"
        assert req.project_id == 0

    async def test_list_results_request_fields(self, creds, fake_sdk):
        client = _make_client(creds)
        await client.list_data_quality_results(
            data_quality_rule_id="r1", bizdate_from="20260701", bizdate_to="20260703"
        )
        name, req = fake_sdk["client"].invocations[0]
        assert name == "list_data_quality_results_async"
        assert req.data_quality_rule_id == "r1"
        assert req.bizdate_from == "20260701"
        assert req.bizdate_to == "20260703"
        assert req.project_id == 0


class TestRetryAndErrors:
    def test_is_retryable_by_code_prefix(self):
        assert _is_retryable(TeaException({"code": "Throttling.User", "message": "m"}))
        assert _is_retryable(TeaException({"code": "ServiceUnavailable", "message": "m"}))

    def test_is_retryable_by_http_status(self):
        exc = TeaException({"code": "X", "message": "m", "data": {"statusCode": 503}})
        assert _is_retryable(exc)

    def test_not_retryable(self):
        assert not _is_retryable(
            TeaException({"code": "InvalidParameter", "message": "m", "data": {"statusCode": 400}})
        )

    async def test_retries_then_succeeds(self, creds, fake_sdk):
        client = _make_client(creds, max_retry=5)
        client._ensure_client()
        fake_sdk["client"].script["get_node_async"] = [
            _throttle(),
            _throttle(),
            _FakeResp({"ok": 1}),
        ]
        body = await client.get_node("n1")
        assert body == {"ok": 1}
        assert len(fake_sdk["client"].invocations) == 3

    async def test_non_retryable_raises_openapierror(self, creds, fake_sdk):
        client = _make_client(creds)
        client._ensure_client()
        fake_sdk["client"].script["get_node_async"] = [
            TeaException({"code": "InvalidParameter", "message": "bad id"})
        ]
        with pytest.raises(OpenAPIError) as exc:
            await client.get_node("n1")
        assert exc.value.code == "InvalidParameter"
        assert "bad id" in exc.value.message
        assert len(fake_sdk["client"].invocations) == 1

    async def test_retry_exhausted_raises(self, creds, fake_sdk):
        client = _make_client(creds, max_retry=3)
        client._ensure_client()
        fake_sdk["client"].script["get_node_async"] = [_throttle(), _throttle(), _throttle()]
        with pytest.raises(OpenAPIError) as exc:
            await client.get_node("n1")
        assert exc.value.code == "Throttling.Api"
        assert len(fake_sdk["client"].invocations) == 3

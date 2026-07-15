from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dataworks_agent.agent.workflow_service import AgentWorkflowService
from dataworks_agent.modeling.standard_oss import (
    build_standard_material_report_ods_artifacts,
    is_standard_material_report,
)
from dataworks_agent.schemas import RootCheckField, RootCheckResult
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def restore_standard_oss_state():
    names = ["_bff_client", "_node_client", "_maxcompute_client", "_publish_gate"]
    before = {name: getattr(app_state, name, None) for name in names}
    for name in names:
        setattr(app_state, name, None)
    yield
    for name, value in before.items():
        setattr(app_state, name, value)


STANDARD_PARAMS = {
    "source_type": "oss",
    "oss_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
    "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
    "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
    "oss_path": "oss://bucket/ads/tiktok/material_report/",
    "file_format": "json",
    "dev_schema": "giikin_develop",
    "prod_schema": "giikin",
    "template_task_id": "10002152501",
    "granularity": "hour",
    "ods_sql_directory": "濞戞挻鑹炬慨鐔访规担琛℃煠/106_妤犵偛鐏濋幉锟犲箮閵夈儲鍟?MaxCompute/闁轰胶澧楀畵浣割嚕閳ь剟宕?00_ODS",
    "dwd_sql_directory": "濞戞挻鑹炬慨鐔访规担琛℃煠/106_妤犵偛鐏濋幉锟犲箮閵夈儲鍟?MaxCompute/闁轰胶澧楀畵浣割嚕閳ь剟宕?02_DWD",
    "json_field_mappings": [
        {"json_key": "material_id", "target_name": "material_id", "type": "STRING"},
        {"json_key": "material_name", "target_name": "material_name", "type": "STRING"},
    ],
    "logical_primary_keys": ["material_id"],
}


def test_standard_oss_builder_rejects_daily_granularity() -> None:
    with pytest.raises(ValueError, match="hourly"):
        from dataworks_agent.modeling.standard_oss import build_standard_material_report_artifacts

        build_standard_material_report_artifacts(
            field_mappings=[{"json_key": "id", "target_name": "id"}],
            logical_primary_keys=["id"],
            granularity="day",
        )


def test_standard_oss_builder_rejects_unknown_logical_key() -> None:
    from dataworks_agent.modeling.standard_oss import build_standard_material_report_artifacts

    with pytest.raises(ValueError, match="not_a_field"):
        build_standard_material_report_artifacts(
            field_mappings=[{"json_key": "id", "target_name": "id"}],
            logical_primary_keys=["not_a_field"],
        )


    oss_path = (
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/"
        "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report"
    )

    assert is_standard_material_report({"source_type": "oss", "oss_path": oss_path}) is True
    assert (
        is_standard_material_report({"source_type": "oss", "oss_path": oss_path + "_other"})
        is False
    )


@pytest.mark.asyncio
async def test_path_only_tiktok_material_report_does_not_hit_generic_target_gate():
    service = AgentWorkflowService()
    message = (
        "oss ??? oss://oss-cn-shenzhen-internal.aliyuncs.com/"
        "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report ????"
    )
    result = await service._forward_model(
        message,
        {
            "source_type": "oss",
            "oss_path": (
                "oss://oss-cn-shenzhen-internal.aliyuncs.com/"
                "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report"
            ),
        },
        "dev_execute",
        initialize_data=True,
        publish=False,
        client_ip="127.0.0.1",
    )

    assert result.success is True
    assert result.data["standard"] == "tiktok_smart_plus_material_report"
    assert result.data["ods_table"] == "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
    assert result.data["dwd_table"] == "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert result.data["missing_context"] == ["cookie_bff"]
    assert result.errors == []


def test_standard_oss_builder_defaults_to_giikin_develop():
    artifacts = build_standard_material_report_ods_artifacts(
        oss_path="oss://bucket/ads/tiktok/material_report/",
        ods_sql_directory="濞戞挻鑹炬慨鐔访规担琛℃煠/106_妤犵偛鐏濋幉锟犲箮閵夈儲鍟?MaxCompute/闁轰胶澧楀畵浣割嚕閳ь剟宕?00_ODS",
    )

    assert artifacts["environment_artifacts"]["dev"]["schema"] == "giikin"
    assert artifacts["environment_artifacts"]["prod"]["schema"] == "giikin"
    assert artifacts["partition_precreate_sql"] == (
        "ALTER TABLE giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour\n"
        "ADD IF NOT EXISTS PARTITION (dt='${gmtdate}', ht='${hour_last1h}');"
    )
    assert "INSERT OVERWRITE TABLE giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour" in artifacts["sql"]
    assert "FROM giikin_develop.tiktok_smart_plus_material_report" in artifacts["sql"]
    assert "LOAD " + "OVERWRITE" not in artifacts["sql"]


def test_standard_oss_builder_preserves_endpoint_in_location():
    artifacts = build_standard_material_report_ods_artifacts(
        oss_path=(
            "oss://oss-cn-shenzhen-internal.aliyuncs.com/"
            "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report"
        ),
        ods_sql_directory="ods/00_ODS",
    )

    assert "FROM giikin_develop.tiktok_smart_plus_material_report" in artifacts["sql"]
    assert "FROM " + "LOCATION" not in artifacts["sql"]
    assert artifacts["sql"].index("ALTER TABLE") < artifacts["sql"].index("INSERT OVERWRITE")


@pytest.mark.asyncio
async def test_standard_oss_table_name_from_ods_request_does_not_override_dwd_default():
    service = AgentWorkflowService()
    result = await service._execute_standard_oss_flow(
        message="standard OSS material report",
        params={
            "source_type": "oss",
            "oss_path": "oss://bucket/ads/tiktok/material_report/",
            "table_name": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
        },
        mode="dev_execute",
        initialize_data=True,
        publish=False,
        client_ip="127.0.0.1",
    )

    assert result.success is True
    assert result.data["dwd_table"] == "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert result.data["missing_context"] == ["cookie_bff"]


@pytest.mark.asyncio
async def test_standard_oss_requires_dwd_directory_and_granularity():
    service = AgentWorkflowService()
    result = await service._execute_standard_oss_flow(
        message="OSS 标准物料报告",
        params={
            "source_type": "oss",
            "oss_path": "oss://bucket/ads/material/",
            "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
        },
        mode="dev_execute",
        initialize_data=True,
        publish=False,
        client_ip="127.0.0.1",
    )

    assert result.success is True
    assert result.data["needs_clarification"] is True
    assert result.data["dwd_table"] == "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert result.data["missing_context"] == ["cookie_bff"]


@pytest.mark.asyncio
async def test_standard_oss_missing_profile_offers_custom_input_actions_without_fake_columns():
    service = AgentWorkflowService()
    app_state._bff_client = object()
    directory = {
        "success": True,
        "ingestion_mode": "raw_json_text",
        "project": "dev",
        "table_name": "material_report",
        "columns": [{"name": "json_data", "type": "STRING"}],
        "directory_check": {"success": True, "channel": "cookie_bff"},
    }

    with (
        patch(
            "dataworks_agent.services.ods_oss.inspect_oss_directory_with_cookie",
            new=AsyncMock(return_value=directory),
        ),
        patch(
            "dataworks_agent.services.ods_oss.discover_oss_schema_with_fallback",
            new=AsyncMock(return_value={"success": False, "columns": []}),
        ),
    ):
        result = await service._execute_standard_oss_flow(
            message="OSS tiktok smart plus material report",
            params={
                "source_type": "oss",
                "oss_path": "oss://bucket/ads/tiktok/material_report/",
                "granularity": "hour",
            },
            mode="dev_execute",
            initialize_data=True,
            publish=False,
            client_ip="127.0.0.1",
        )

    assert result.success is True
    assert result.data["missing_context"] == ["data_profile"]
    actions = result.data["next_actions"]
    assert [action["id"] for action in actions] == [
        "provide_data_profile",
        "provide_data_profile_columns",
    ]
    assert all(action["requires_custom_input"] for action in actions)
    assert all("payload" not in action for action in actions)


@pytest.mark.asyncio
async def test_standard_oss_full_flow_uses_cookie_for_dev_and_requested_node_directory():
    service = AgentWorkflowService()

    class FakeBff:
        project_id = "project-1"
        last_error = None

        async def create_node(self, name, path, language="odps-sql"):
            self.created_node = (name, path, language)
            return "dwd-node-1"

        async def update_node(self, uuid, content):
            self.updated_node = (uuid, content)
            return True

        async def update_vertex(self, uuid, config):
            self.vertex = (uuid, config)
            return True

        async def _put(self, path, payload):
            self.dependency_call = (path, payload)
            return {"code": 200}

    app_state._bff_client = FakeBff()
    root_result = RootCheckResult(
        passed=True,
        field_results=[RootCheckField(field_name="material_id", valid=True)],
        summary="0/2 invalid fields (online synced root dictionary)",
        source="online",
    )
    directory = {
        "success": True,
        "ingestion_mode": "raw_json_text",
        "project": "dev",
        "table_name": "material_report",
        "columns": [{"name": "json_data", "type": "STRING"}],
        "directory_check": {
            "success": True,
            "channel": "cookie_bff",
            "bucket": "bucket",
            "prefix": "ads/tiktok/material_report/",
        },
    }
    profile = {
        "success": True,
        "columns": [
            {"name": "material_id", "type": "STRING"},
            {"name": "material_name", "type": "STRING"},
        ],
    }
    pipeline_result = {
        "success": True,
        "node_uuid": "node-1",
        "steps": {"publish": {"status": "skipped"}},
    }
    created_tables = []

    async def create_table(ddl: str, schema: str, target_table: str):
        created_tables.append((schema, target_table, ddl))
        return {"status": "created", "schema": schema, "table": target_table}

    class FakePipeline:
        def __init__(self, bff):
            assert bff is app_state._bff_client

        async def run(self, **kwargs):
            assert kwargs["node_path_prefix"] == STANDARD_PARAMS["ods_sql_directory"]
            assert kwargs["publish"] is False
            assert kwargs["ingestion_mode"] == "raw_json_text"
            return pipeline_result

    with (
        patch(
            "dataworks_agent.services.ods_oss.inspect_oss_directory_with_cookie",
            new=AsyncMock(return_value=directory),
        ),
        patch(
            "dataworks_agent.services.ods_oss.discover_oss_schema_with_fallback",
            new=AsyncMock(return_value=profile),
        ),
        patch(
            "dataworks_agent.modeling.root_checker.RootChecker.check_fields",
            new=AsyncMock(return_value=root_result),
        ),
        patch("dataworks_agent.services.ods_oss.OssImportPipeline", new=FakePipeline),
        patch.object(service, "_create_table_cookie", new=AsyncMock(side_effect=create_table)),
    ):
        result = await service._execute_standard_oss_flow(
            message="闁哄秴娲ら崳?OSS tiktok smart plus material report",
            params=STANDARD_PARAMS,
            mode="dev_execute",
            initialize_data=True,
            publish=False,
            client_ip="127.0.0.1",
        )

    assert result.success is True
    assert [item[:2] for item in created_tables] == [
        ("giikin", "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"),
        ("giikin", "dwd_mkt_tiktok_smart_plus_material_report_hour"),
    ]
    assert result.data["prod_tables"]["ods"]["status"] == "approval_required"
    assert result.data["prod_tables"]["dwd"]["status"] == "approval_required"
    assert result.data["template_task_id"] == "10002152501"
    assert result.data["checker"] == "dmr_pub_column_check"
    assert result.data["ods_pipeline"] == pipeline_result
    assert (
        result.data["dwd_pipeline"]["node_path"]
        == f"{STANDARD_PARAMS['dwd_sql_directory']}/{STANDARD_PARAMS['dwd_table']}"
    )
    assert result.data["dwd_pipeline"]["dependency_status"] == "cookie_bff"
    assert (
        result.data["dwd_pipeline"]["dependencies"][0]["output"]
        == "giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
    )


@pytest.mark.asyncio
async def test_standard_oss_root_failure_blocks_table_creation():
    service = AgentWorkflowService()
    app_state._bff_client = object()
    root_result = RootCheckResult(
        passed=False,
        field_results=[
            RootCheckField(field_name="bad_token", valid=False, invalid_segments=["bad"])
        ],
        summary="1/1 invalid fields",
        source="online",
    )

    with (
        patch(
            "dataworks_agent.services.ods_oss.inspect_oss_directory_with_cookie",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "ingestion_mode": "raw_json_text",
                    "project": "dev",
                    "table_name": "material_report",
                    "columns": [{"name": "json_data", "type": "STRING"}],
                    "directory_check": {"success": True},
                }
            ),
        ),
        patch(
            "dataworks_agent.services.ods_oss.discover_oss_schema_with_fallback",
            new=AsyncMock(return_value={"success": True, "columns": [{"name": "bad_token"}]}),
        ),
        patch(
            "dataworks_agent.modeling.root_checker.RootChecker.check_fields",
            new=AsyncMock(return_value=root_result),
        ),
        patch.object(service, "_create_table_cookie", new=AsyncMock()) as create_table,
    ):
        params = dict(STANDARD_PARAMS)
        params["json_field_mappings"] = [
            {"json_key": "bad", "target_name": "bad_token", "type": "STRING"}
        ]
        result = await service._execute_standard_oss_flow(
            message="闁哄秴娲ら崳?OSS tiktok smart plus material report",
            params=params,
            mode="dev_execute",
            initialize_data=True,
            publish=False,
            client_ip="127.0.0.1",
        )

    assert result.success is False
    assert result.steps[-1]["step"] == "dmr_pub_column_check"
    assert result.steps[-1]["status"] == "failed"
    create_table.assert_not_awaited()


@pytest.mark.asyncio
async def test_standard_oss_requires_oss_directory_before_cookie_inspection():
    service = AgentWorkflowService()
    result = await service._execute_standard_oss_flow(
        message="standard OSS material report",
        params={
            "source_type": "oss",
            "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
            "ods_sql_directory": "ods/00_ODS",
            "dwd_sql_directory": "dwd/02_DWD",
            "granularity": "hour",
        },
        mode="dev_execute",
        initialize_data=True,
        publish=False,
        client_ip="127.0.0.1",
    )

    assert result.success is True
    assert result.data["missing_context"] == ["oss_path"]
    assert result.data["needs_clarification"] is True

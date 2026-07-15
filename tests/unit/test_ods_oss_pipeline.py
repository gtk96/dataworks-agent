from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from dataworks_agent.services.ods_oss.pipeline import OssImportPipeline


class FakeNodeClient:
    def __init__(self) -> None:
        self.last_error = ""
        self.create_node = AsyncMock(return_value="existing-or-new-node")
        self.update_node = AsyncMock(return_value=True)
        self.update_vertex = AsyncMock(return_value=True)
        self.deploy_nodes = AsyncMock(return_value=True)
        self.execute_sql_ida = AsyncMock(return_value="job-1")
        self.wait_ida_job = AsyncMock(return_value=True)
        self.list_datasources = AsyncMock(return_value=[])


@pytest.mark.asyncio
async def test_oss_pipeline_writes_partition_root_dependency_and_single_output():
    client = FakeNodeClient()
    result = await OssImportPipeline(client).run(
        oss_path=(
            "oss://oss-cn-shenzhen-internal.aliyuncs.com/"
            "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report"
        ),
        target_table="ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
        file_format="json",
        schedule_type="hour",
        node_path_prefix="????/106_????/MaxCompute/????/00_ODS",
        publish=False,
        ingestion_mode="raw_json_text",
        root_node_uuid="32257551",
        output_ref="giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
        source_partition_value="2026071412",
    )

    assert result["success"] is True
    assert "ALTER TABLE giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour" in result["sql"]
    assert "INSERT OVERWRITE TABLE giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour" in result["sql"]
    assert "FROM giikin_develop.tiktok_smart_plus_material_report" in result["sql"]
    assert "LOAD " + "OVERWRITE" not in result["sql"]
    assert result["dependencies"][0] == {
        "type": "Normal",
        "sourceType": "System",
        "output": "32257551",
        "refTableName": "32257551",
    }
    assert result["dependencies"][1]["type"] == "CrossCycleDependsOnSelf"
    assert result["outputs"] == {
        "nodeOutputs": [
            {
                "artifactType": "NodeOutput",
                "sourceType": "System",
                "data": "giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
                "refTableName": "giikin.ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
                "isDefault": True,
            }
        ]
    }
    config = client.update_vertex.await_args.args[1]
    assert config["dependencies"] == result["dependencies"]
    assert config["outputs"] == result["outputs"]


@pytest.mark.asyncio
async def test_oss_pipeline_refuses_to_create_without_root_context(monkeypatch):
    monkeypatch.setattr("dataworks_agent.services.ods_oss.pipeline.settings.dataworks_default_root_node_uuid", "")
    monkeypatch.setattr("dataworks_agent.services.ods_oss.pipeline.settings.root_check_node_uuid", "")
    client = FakeNodeClient()
    result = await OssImportPipeline(client).run(
        oss_path="oss://bucket/data/",
        target_table="ods_oss_test_hour",
        file_format="csv",
        publish=False,
        root_node_uuid="",
    )

    assert result["success"] is False
    assert result["steps"]["configure_dependencies"]["status"] == "needs_context"
    client.create_node.assert_not_awaited()

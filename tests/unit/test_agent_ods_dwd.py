"""Agent ODS+DWD conversational capability tests."""

from __future__ import annotations

import pytest

from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.agent.executor.tool_executor import ToolExecutor
from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.agent.planner.task_planner import TaskPlanner

MYSQL_ODS_DWD = (
    "\u628a mysql \u6570\u636e\u6e90 jky_singleshop \u7684 orders "
    "\u8868\u505a\u6210\u5c0f\u65f6 ODS\uff0c\u518d\u57fa\u4e8e\u5b83\u5efa "
    "dwd_trade_order_detail"
)
EXISTING_ODS_DWD = "\u57fa\u4e8e ods_order \u8bbe\u8ba1 dwd_trade_order_detail"
HOLO_ODS_DWD = (
    "\u628a Hologres \u6570\u636e\u6e90 dataworks_holo \u7684 ofc_order_fulfillment "
    "\u8868\u505a ODS Holo\uff0c\u518d\u5efa dwd_order_fulfillment_detail"
)

OSS_ODS_DWD = (
    "\u628a OSS \u8def\u5f84 oss://dw-bucket/import/orders.csv "
    "\u505a ODS\uff0c\u518d\u5efa dwd_oss_order_detail"
)
REALTIME_ODS_DWD = (
    "\u628a mysql \u6570\u636e\u6e90 jky_singleshop \u7684 orders "
    "\u8868\u505a\u5b9e\u65f6 ODS\uff0c\u518d\u5efa dwd_trade_order_rt_detail"
)


def test_parser_extracts_endpoint_oss_path_and_json_format_from_followup() -> None:
    message = (
        "oss 数据源 sample_material_report 建模处理\n"
        "补充信息：oss://oss-cn-shenzhen-internal.aliyuncs.com/"
        "example-data-bucket/ads/data/sample_material_report/ 字段是 json"
    )

    intent = IntentParser().parse(message)

    assert intent.action in {"agent_workflow", "ods_dwd_modeling", "forward_modeling"}
    assert intent.params["source_type"] == "oss"
    assert intent.params["datasource_name"] == "sample_material_report"
    assert intent.params["file_format"] == "json"
    assert intent.params["oss_path"].endswith("/sample_material_report/")


def test_parser_extracts_multiple_json_mappings_and_composite_logical_key() -> None:
    message = (
        "OSS ODS ods_mc_ads_data__tiktok_smart_plus_material_report_hour，"
        "DWD dwd_mkt_tiktok_smart_plus_material_report_hour，"
        "JSON映射：material_id -> material_id, material_name -> material_name，"
        "逻辑主键：material_id+material_name，DWD粒度：hour"
    )

    params = IntentParser().parse(message).params

    assert params["json_field_mappings"] == [
        {"json_key": "material_id", "target_name": "material_id"},
        {"json_key": "material_name", "target_name": "material_name"},
    ]
    assert params["logical_primary_keys"] == ["material_id", "material_name"]
    assert params["granularity"] == "hour"


def test_parser_recognizes_mysql_ods_dwd_entities() -> None:
    intent = IntentParser().parse(MYSQL_ODS_DWD)

    assert intent.action == "ods_dwd_modeling"
    assert intent.params["source_type"] == "mysql"
    assert intent.params["datasource_name"] == "jky_singleshop"
    assert intent.params["source_table"] == "orders"
    assert intent.params["dwd_table"] == "dwd_trade_order_detail"
    assert intent.params["table_name"] == "dwd_trade_order_detail"
    assert intent.params["granularity"] == "hour"
    assert intent.params["schedule_cycle"] == "hourly"


def test_planner_adds_ods_dwd_steps() -> None:
    intent = IntentParser().parse(MYSQL_ODS_DWD)
    plan = TaskPlanner().plan(intent)
    tools = [step.tool for step in plan.steps]

    assert plan.summary == "Conversational ODS to DWD modeling proposal"
    assert tools == [
        "analyze_ods_dwd_requirement",
        "classify_ods_source",
        "plan_ods_pipeline",
        "preview_dwd_artifacts",
        "plan_ods_dwd_dependencies",
        "validate_guardrails",
        "recommend_next_actions",
    ]
    preview_step = next(step for step in plan.steps if step.tool == "preview_dwd_artifacts")
    assert preview_step.params["datasource_name"] == "jky_singleshop"


def test_standard_oss_tools_use_repository_table_naming_without_user_targets() -> None:
    params = (
        IntentParser()
        .parse(
            "OSS ??? oss://oss-cn-shenzhen-internal.aliyuncs.com/"
            "giikin-dataworks-shenzhen/ads/data/tiktok_smart_plus_material_report ??"
        )
        .params
    )
    executor = ToolExecutor()

    analysis = executor.execute("analyze_ods_dwd_requirement", params)
    ods_plan = executor.execute("plan_ods_pipeline", params)
    dwd_preview = executor.execute("preview_dwd_artifacts", params)
    dependency_plan = executor.execute("plan_ods_dwd_dependencies", params)

    expected_ods = "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
    expected_dwd = "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert analysis.data["ods_table"] == expected_ods
    assert analysis.data["dwd_table"] == expected_dwd
    assert "dwd_table" not in analysis.data["missing_context"]
    assert ods_plan.data["ods_plan"]["target_table"] == expected_ods
    assert dwd_preview.data["dwd_table"] == expected_dwd
    assert dwd_preview.data["missing_context"] == ["json_field_mappings"]
    assert (
        dependency_plan.data["dependency_plan"]["target_output"] == f"giikin_develop.{expected_dwd}"
    )


def test_tool_executor_plans_mysql_ods_and_dwd_preview() -> None:
    params = IntentParser().parse(MYSQL_ODS_DWD).params
    executor = ToolExecutor()

    ods_result = executor.execute("plan_ods_pipeline", params)
    dwd_result = executor.execute("preview_dwd_artifacts", params)

    assert ods_result.success is True
    assert ods_result.data is not None
    assert ods_result.data["ods_plan"]["route"] == "ods_di"
    assert ods_result.data["ods_plan"]["pipeline"] == "DIPipeline.run"
    assert ods_result.data["ods_plan"]["target_table"] == "ods_ms_jky_singleshop__orders_hour"

    assert dwd_result.success is True
    assert dwd_result.data is not None
    assert dwd_result.data["dwd_preview"]["source_table"] == "ods_ms_jky_singleshop__orders_hour"
    assert "create table dwd_trade_order_detail" in dwd_result.data["ddl"]
    assert "INSERT OVERWRITE TABLE dwd_trade_order_detail" in dwd_result.data["sql"]


@pytest.mark.asyncio
async def test_chat_agent_full_ods_dwd_flow_collects_artifacts() -> None:
    response = await ChatAgent().chat(MYSQL_ODS_DWD)

    assert response.success is True
    assert response.data["intent"]["action"] == "ods_dwd_modeling"
    assert response.data["agent_mode"] == "approval_required"
    assert response.data["approvals"]
    artifacts = response.data["artifacts"]
    assert artifacts["ods_plan"]["target_table"] == "ods_ms_jky_singleshop__orders_hour"
    assert artifacts["dwd_preview"]["target_table"] == "dwd_trade_order_detail"
    assert artifacts["dependency_plan"]["upstream_refs"] == [
        "dataworks.ods_ms_jky_singleshop__orders_hour"
    ]


@pytest.mark.asyncio
async def test_chat_agent_existing_ods_to_dwd_skips_ods_create() -> None:
    response = await ChatAgent().chat(EXISTING_ODS_DWD)

    assert response.success is True
    artifacts = response.data["artifacts"]
    assert artifacts["ods_plan"]["route"] == "existing_ods"
    assert artifacts["dwd_preview"]["source_table"] == "ods_order"
    assert "FROM ods_order T1" in artifacts["dwd_preview"]["sql"]


def test_hologres_source_routes_to_ods_holo() -> None:
    params = IntentParser().parse(HOLO_ODS_DWD).params
    result = ToolExecutor().execute("classify_ods_source", params)

    assert params["source_type"] == "hologres"
    assert params["datasource_name"] == "dataworks_holo"
    assert result.success is True
    assert result.data is not None
    assert result.data["ods_route"]["route"] == "ods_holo"
    assert "ods_holo" in result.data["ods_route"]["module"]


def test_oss_source_routes_to_ods_oss_and_derives_table_from_path() -> None:
    params = IntentParser().parse(OSS_ODS_DWD).params
    executor = ToolExecutor()

    route_result = executor.execute("classify_ods_source", params)
    plan_result = executor.execute("plan_ods_pipeline", params)

    assert params["source_type"] == "oss"
    assert params["oss_path"] == "oss://dw-bucket/import/orders.csv"
    assert route_result.data is not None
    assert route_result.data["ods_route"]["route"] == "ods_oss"
    assert plan_result.data is not None
    assert plan_result.data["ods_plan"]["target_table"] == "ods_oss_src__orders_day"


def test_realtime_source_takes_precedence_over_underlying_mysql() -> None:
    params = IntentParser().parse(REALTIME_ODS_DWD).params
    result = ToolExecutor().execute("plan_ods_pipeline", params)

    assert params["source_type"] == "realtime"
    assert params["datasource_name"] == "jky_singleshop"
    assert params["source_table"] == "orders"
    assert result.data is not None
    assert result.data["ods_plan"]["route"] == "ods_realtime"
    assert result.data["ods_plan"]["target_table"] == "ods_mc_jky_singleshop__orders_hour"


@pytest.mark.asyncio
async def test_chat_agent_ods_dwd_missing_context_asks_clarifying_questions() -> None:
    response = await ChatAgent().chat("\u5e2e\u6211\u505a ODS \u518d\u505a DWD")

    assert response.success is True
    assert response.data["intent"]["action"] == "ods_dwd_modeling"
    assert response.data["agent_mode"] == "needs_context"
    assert response.data["clarifying_questions"]


STANDARD_MATERIAL_REPORT_MESSAGE = (
    "OSS ODS ods_mc_ads_data__tiktok_smart_plus_material_report_hour "
    "\u4e3a\u57fa\u51c6\uff0c\u5f00\u53d1\u5e93 giikin_develop,\u4e0b\u6e38 DWD dwd_mkt_tiktok_smart_plus_material_report_hour,"
    "\u4efb\u52a1 id:10002152501"
)


def test_parser_extracts_separate_dwd_sql_directory() -> None:
    intent = IntentParser().parse(
        STANDARD_MATERIAL_REPORT_MESSAGE
        + " ODS SQL目录：业务流程/106_广告报告/MaxCompute/数据开发/00_ODS"
        + " DWD SQL目录：业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"
    )

    assert intent.params["ods_sql_directory"].endswith("00_ODS")
    assert intent.params["dwd_sql_directory"].endswith("02_DWD")


def test_parser_preserves_standard_material_report_ods_and_template_task() -> None:
    intent = IntentParser().parse(STANDARD_MATERIAL_REPORT_MESSAGE)

    assert intent.action == "ods_dwd_modeling"
    assert intent.params["ods_table"] == "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
    assert intent.params["dwd_table"] == "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert intent.params["task_id"] == "10002152501"
    assert intent.params["standard_oss_json"] is True
    assert intent.params["dev_schema"] == "giikin_develop"


def test_standard_material_report_without_mapping_does_not_invent_dwd_fields() -> None:
    result = ToolExecutor().execute(
        "preview_dwd_artifacts",
        {
            "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
            "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
            "task_id": "10002152501",
        },
    )

    assert result.success is True
    assert result.data is not None
    assert result.data["mode"] == "needs_context"
    assert result.data["dwd_table"] == "dwd_mkt_tiktok_smart_plus_material_report_hour"
    assert "json_field_mappings" in result.data["missing_context"]
    assert "sample_material_report" not in str(result.data)


def test_standard_material_report_uses_json_tuple_roots_and_template_schedule() -> None:
    result = ToolExecutor().execute(
        "preview_dwd_artifacts",
        {
            "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
            "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
            "task_id": "10002152501",
            "dev_schema": "giikin_develop",
            "json_field_mappings": [
                {"json_key": "material_id", "target_name": "material_id", "type": "STRING"},
                {"json_key": "material_name", "target_name": "material_name", "type": "STRING"},
                {"json_key": "spend", "target_name": "spend_amt", "type": "DECIMAL(18,2)"},
            ],
        },
    )

    assert result.success is True
    assert result.data is not None
    assert "LATERAL VIEW OUTER JSON_TUPLE" in result.data["sql"]
    assert "get_json_object" not in result.data["sql"]
    assert (
        "INSERT OVERWRITE TABLE giikin_develop.dwd_mkt_tiktok_smart_plus_material_report_hour"
        in result.data["sql"]
    )
    assert (
        "FROM giikin_develop.ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
        in result.data["sql"]
    )
    assert "${gmtdate}" in result.data["sql"]
    assert "${hour_last1h}" in result.data["sql"]
    assert "json_data" not in result.data["ddl"]
    assert result.data["validation"]["passed"] is True
    assert result.data["validation"]["root_source"] == "online"
    assert result.data["schedule"]["cron"] == "00 03 00-23/1 * * ?"
    assert result.data["schedule"]["template_task_id"] == "10002152501"


def test_standard_material_report_invalid_root_blocks_preview() -> None:
    result = ToolExecutor().execute(
        "preview_dwd_artifacts",
        {
            "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
            "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
            "task_id": "10002152501",
            "dev_schema": "giikin_develop",
            "json_field_mappings": [
                {"json_key": "material_id", "target_name": "zzzz_bad_token", "type": "STRING"},
            ],
        },
    )

    assert result.success is False
    assert result.error == "standard_oss_json_validation_failed"
    assert result.data is not None
    assert result.data["validation"]["root_check"]["passed"] is False


def test_standard_material_report_dependency_plan_reuses_structure_not_template_business_parents() -> (
    None
):
    result = ToolExecutor().execute(
        "plan_ods_dwd_dependencies",
        {
            "ods_table": "ods_mc_ads_data__tiktok_smart_plus_material_report_hour",
            "dwd_table": "dwd_mkt_tiktok_smart_plus_material_report_hour",
            "task_id": "10002152501",
            "dev_schema": "giikin_develop",
        },
    )

    assert result.success is True
    assert result.data is not None
    plan = result.data["dependency_plan"]
    assert plan["dev_schema"] == "giikin_develop"
    assert plan["upstream_refs"] == [
        "giikin_develop.ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
    ]
    assert plan["schedule"]["parameters"] == ["gmtdate", "hour_last1h"]
    assert plan["template_parent_references_are_reference_only"] is True
    assert plan["template_task_id"] == "10002152501"

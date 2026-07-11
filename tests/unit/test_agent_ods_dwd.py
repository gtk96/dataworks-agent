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

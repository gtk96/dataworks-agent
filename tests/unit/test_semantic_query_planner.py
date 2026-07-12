from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.workflow_service import (
    AgentWorkflowService,
    QueryNeedsClarificationError,
)
from dataworks_agent.semantic.album_context import AlbumTable, DataAlbumContext
from dataworks_agent.semantic.layer import SemanticDefinition
from dataworks_agent.semantic.query_planner import MetricQueryPlanner
from dataworks_agent.state import app_state


def order_album() -> list[DataAlbumContext]:
    return [
        DataAlbumContext(
            album_id=888,
            name="订单",
            categories=["订单指标"],
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_rp_ord_order_cnt_hi",
                    comment="当日小时订单量预警表",
                    remark="有效订单认证指标表",
                )
            ],
        )
    ]


def test_total_effective_order_is_built_from_certified_metric_and_album():
    plan = MetricQueryPlanner().plan("今天的总有效订单是多少", order_album())

    assert plan is not None
    assert plan.metric_id == "effective_order_cnt"
    assert plan.albums[0]["name"] == "订单"
    assert plan.selected_dimensions == []
    assert "total_effective_order_cnt" in plan.sql
    assert "family_name = '合计'" in plan.sql
    assert "LIMIT 2" in plan.sql


def test_family_effective_order_selects_dimension_from_semantic_contract():
    plan = MetricQueryPlanner().plan("查一下今天各家族的有效订单数", order_album())

    assert plan is not None
    assert plan.selected_dimensions == ["家族"]
    assert "family_name <> '合计'" in plan.sql
    assert "ORDER BY effective_order_cnt DESC" in plan.sql


def test_latest_snapshot_metric_does_not_guess_historical_time_scope():
    planner = MetricQueryPlanner()

    assert planner.plan("上个月的有效订单是多少", order_album()) is None
    assert planner.candidate_tables("上个月的有效订单是多少") == set()


def test_certified_metric_cannot_bypass_album_membership():
    planner = MetricQueryPlanner()
    wrong_album = [
        DataAlbumContext(
            album_id=1,
            name="订单",
            tables=[AlbumTable(project="p", name="tb_dwd_other")],
        )
    ]

    assert planner.has_certified_metric("今天有效订单是多少") is True
    assert planner.plan("今天有效订单是多少", wrong_album) is None


@pytest.mark.asyncio
async def test_metadata_validation_checks_measure_dimensions_filters_and_partitions():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan("今天各家族有效订单是多少", order_album())
    assert plan is not None
    ddl = """
CREATE TABLE tb_rp_ord_order_cnt_hi (
  family_name STRING,
  line_name STRING,
  befrom STRING,
  statis_type STRING,
  time_interval STRING,
  effective_order_cnt BIGINT
)
PARTITIONED BY (pt STRING, ht STRING)
"""
    before = getattr(app_state, "_bff_client", None)
    app_state._bff_client = SimpleNamespace(get_creation_ddl=AsyncMock(return_value=ddl))
    try:
        await service._validate_semantic_plan_metadata(plan)
    finally:
        app_state._bff_client = before

    assert plan.metadata_validation["status"] == "passed"
    assert "family_name" in plan.metadata_validation["required_fields"]
    assert "真实 DDL" in plan.selection_evidence[-1]


@pytest.mark.asyncio
async def test_total_metric_rejects_duplicate_summary_rows():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan("今天总有效订单是多少", order_album())
    assert plan is not None

    result = await service._query_success(
        plan,
        [plan.semantic_artifact()],
        ["data_date", "data_hour", "total_effective_order_cnt"],
        [["20260712", "13", "10"], ["20260712", "13", "11"]],
        "cookie_bff",
    )

    assert result.success is False
    assert "唯一命中 1 行" in result.message
    assert result.steps[-1]["step"] == "validate_metric_uniqueness"


def test_approved_semantic_layer_definition_overrides_bundled_baseline():
    body = json.loads(Path("dataworks_agent/semantic/metrics.json").read_text(encoding="utf-8"))[
        "metrics"
    ][0]
    body["table"] = "giikin_aliyun.tb_rp_ord_order_cnt_hi_v2"
    semantic_layer = SimpleNamespace(
        list_definitions=lambda **kwargs: [
            SemanticDefinition(
                def_id="sem_v2",
                kind="metric",
                key="effective_order_cnt",
                body=body,
                version=2,
                source="manual",
                status="approved",
            )
        ]
    )
    album = order_album()
    album[0].tables.append(
        AlbumTable(
            project="giikin_aliyun",
            name="tb_rp_ord_order_cnt_hi_v2",
            comment="\u65b0\u7248\u8ba4\u8bc1\u8868",
        )
    )

    plan = MetricQueryPlanner(semantic_layer=semantic_layer).plan(
        "\u4eca\u5929\u603b\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11", album
    )

    assert plan is not None
    assert plan.metric_version == 2
    assert plan.table.endswith("_v2")
    assert "tb_rp_ord_order_cnt_hi_v2" in plan.sql


def test_incomplete_approved_definition_cannot_override_executable_baseline():
    semantic_layer = SimpleNamespace(
        list_definitions=lambda **kwargs: [
            SemanticDefinition(
                def_id="sem_broken",
                kind="metric",
                key="effective_order_cnt",
                body={"name": "\u6709\u6548\u8ba2\u5355\u6570"},
                version=99,
                status="approved",
            )
        ]
    )

    plan = MetricQueryPlanner(semantic_layer=semantic_layer).plan(
        "\u4eca\u5929\u603b\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11", order_album()
    )

    assert plan is not None
    assert plan.metric_version == 1
    assert plan.table == "giikin_aliyun.tb_rp_ord_order_cnt_hi"


@pytest.mark.asyncio
async def test_metadata_validation_prefers_maxcompute_ak_sk():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan(
        "\u4eca\u5929\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11", order_album()
    )
    assert plan is not None
    ddl = """
CREATE TABLE tb_rp_ord_order_cnt_hi (
  family_name STRING, line_name STRING, befrom STRING, statis_type STRING,
  time_interval STRING, effective_order_cnt BIGINT
) PARTITIONED BY (pt STRING, ht STRING)
"""
    before_mc = getattr(app_state, "_maxcompute_client", None)
    before_bff = getattr(app_state, "_bff_client", None)
    mc = SimpleNamespace(get_table_ddl=AsyncMock(return_value=ddl))
    bff = SimpleNamespace(get_creation_ddl=AsyncMock(return_value=ddl))
    app_state._maxcompute_client = mc
    app_state._bff_client = bff
    try:
        await service._validate_semantic_plan_metadata(plan)
    finally:
        app_state._maxcompute_client = before_mc
        app_state._bff_client = before_bff

    assert plan.metadata_validation["channel"] == "maxcompute_ak_sk"
    mc.get_table_ddl.assert_awaited_once_with("tb_rp_ord_order_cnt_hi", project="giikin_aliyun")
    bff.get_creation_ddl.assert_not_awaited()


@pytest.mark.asyncio
async def test_certified_metric_is_blocked_without_any_metadata_channel():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan(
        "\u4eca\u5929\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11", order_album()
    )
    assert plan is not None
    before_mc = getattr(app_state, "_maxcompute_client", None)
    before_bff = getattr(app_state, "_bff_client", None)
    app_state._maxcompute_client = None
    app_state._bff_client = None
    try:
        with pytest.raises(QueryNeedsClarificationError) as raised:
            await service._validate_semantic_plan_metadata(plan)
        assert "\u672a\u7ecf\u7ed3\u6784\u6838\u9a8c" in raised.value.reason
    finally:
        app_state._maxcompute_client = before_mc
        app_state._bff_client = before_bff

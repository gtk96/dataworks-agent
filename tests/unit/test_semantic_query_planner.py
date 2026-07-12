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
            categories=["订单"],
            tables=[
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dws_ord_order_si_crt_df",
                    comment="订单指标汇总表，保存订单相关高度汇总数据，按订单创建时间分区存储",
                    entity_guid="odps.giikin_aliyun.tb_dws_ord_order_si_crt_df",
                    qualified_name="maxcompute-table.giikin_aliyun.tb_dws_ord_order_si_crt_df",
                    relation_id=8836,
                ),
                AlbumTable(
                    project="giikin_aliyun",
                    name="tb_dwd_ord_gk_order_info_crt_df",
                    comment="订单表-按照创建时间存储",
                    entity_guid="odps.giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df",
                    qualified_name="maxcompute-table.giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df",
                    relation_id=8837,
                ),
            ],
        )
    ]


def test_total_effective_order_is_built_from_certified_metric_and_album():
    plan = MetricQueryPlanner().plan("今天的总有效订单是多少", order_album())

    assert plan is not None
    assert plan.metric_id == "effective_order_cnt"
    assert plan.metric_version == 2
    assert plan.albums[0]["name"] == "订单"
    assert plan.album_validation["status"] == "direct_match"
    assert plan.album_validation["assets"][0]["relation_id"] == 8836
    assert plan.selected_dimensions == []
    assert "SUM(effect_order_cnt) AS total_effective_order_cnt" in plan.sql
    assert "FROM giikin_aliyun.tb_dws_ord_order_si_crt_df" in plan.sql
    assert "GROUP BY pt" in plan.sql
    assert "LIMIT 1" in plan.sql
    assert "COUNT(*) AS total_effective_order_cnt" in plan.reconciliation_sql
    assert "FROM giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df" in plan.reconciliation_sql
    assert "is_effective_order = 1" in plan.reconciliation_sql


def test_family_effective_order_selects_dimension_from_semantic_contract():
    plan = MetricQueryPlanner().plan("查一下今天各家族的有效订单数", order_album())

    assert plan is not None
    assert plan.selected_dimensions == ["家族"]
    assert "family_name" in plan.sql
    assert "SUM(effect_order_cnt) AS effective_order_cnt" in plan.sql
    assert "GROUP BY pt, family_name" in plan.sql
    assert "ORDER BY effective_order_cnt DESC" in plan.sql
    assert "GROUP BY pt, family_name" in plan.reconciliation_sql


def test_latest_snapshot_metric_does_not_guess_historical_time_scope():
    planner = MetricQueryPlanner()

    assert planner.plan("上个月的有效订单是多少", order_album()) is None
    assert planner.candidate_tables("上个月的有效订单是多少") == set()


def test_certified_metric_is_ungrounded_when_table_is_not_in_album():
    planner = MetricQueryPlanner()
    order_domain_album = [
        DataAlbumContext(
            album_id=1,
            name="订单",
            tables=[AlbumTable(project="p", name="tb_dwd_other")],
        )
    ]

    assert planner.has_certified_metric("今天有效订单是多少") is True
    plan = planner.plan("今天有效订单是多少", order_domain_album)

    assert plan is not None
    assert plan.albums == []
    assert plan.album_validation == {
        "status": "ungrounded",
        "certified_table_present": False,
        "assets": [],
        "required_album_id": 888,
        "required_tables": [
            "giikin_aliyun.tb_dws_ord_order_si_crt_df",
            "giikin_aliyun.tb_dwd_ord_gk_order_info_crt_df",
        ],
    }
    assert "禁止执行" in plan.selection_evidence[1]


@pytest.mark.asyncio
async def test_metadata_validation_checks_measure_dimensions_filters_and_partitions():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan("今天各家族有效订单是多少", order_album())
    assert plan is not None
    ddl = """
CREATE TABLE tb_dws_ord_order_si_crt_df (
  crt_time STRING,
  family_name STRING,
  effect_order_cnt BIGINT
)
PARTITIONED BY (pt STRING)
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
        ["data_date", "total_effective_order_cnt"],
        [["20260712", "10"], ["20260712", "11"]],
        "cookie_bff",
    )

    assert result.success is False
    assert "唯一命中 1 行" in result.message
    assert result.steps[-1]["step"] == "validate_metric_uniqueness"


def test_approved_semantic_layer_definition_overrides_bundled_baseline():
    body = json.loads(Path("dataworks_agent/semantic/metrics.json").read_text(encoding="utf-8"))[
        "metrics"
    ][0]
    body["table"] = "giikin_aliyun.tb_dws_ord_order_si_crt_df_v3"
    body["version"] = 3
    semantic_layer = SimpleNamespace(
        list_definitions=lambda **kwargs: [
            SemanticDefinition(
                def_id="sem_v3",
                kind="metric",
                key="effective_order_cnt",
                body=body,
                version=3,
                source="manual",
                status="approved",
            )
        ]
    )
    album = order_album()
    album[0].tables.append(
        AlbumTable(
            project="giikin_aliyun",
            name="tb_dws_ord_order_si_crt_df_v3",
            comment="新版认证表",
        )
    )

    plan = MetricQueryPlanner(semantic_layer=semantic_layer).plan("今天总有效订单是多少", album)

    assert plan is not None
    assert plan.metric_version == 3
    assert plan.table.endswith("_v3")
    assert "tb_dws_ord_order_si_crt_df_v3" in plan.sql


def test_incomplete_approved_definition_cannot_override_executable_baseline():
    semantic_layer = SimpleNamespace(
        list_definitions=lambda **kwargs: [
            SemanticDefinition(
                def_id="sem_broken",
                kind="metric",
                key="effective_order_cnt",
                body={"name": "有效订单数"},
                version=99,
                status="approved",
            )
        ]
    )

    plan = MetricQueryPlanner(semantic_layer=semantic_layer).plan(
        "今天总有效订单是多少", order_album()
    )

    assert plan is not None
    assert plan.metric_version == 2
    assert plan.table == "giikin_aliyun.tb_dws_ord_order_si_crt_df"


@pytest.mark.asyncio
async def test_metadata_validation_prefers_maxcompute_ak_sk():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan("今天有效订单是多少", order_album())
    assert plan is not None
    ddl = """
CREATE TABLE tb_dws_ord_order_si_crt_df (
  crt_time STRING, family_name STRING, effect_order_cnt BIGINT
) PARTITIONED BY (pt STRING)
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
    mc.get_table_ddl.assert_awaited_once_with("tb_dws_ord_order_si_crt_df", project="giikin_aliyun")
    bff.get_creation_ddl.assert_not_awaited()


@pytest.mark.asyncio
async def test_certified_metric_is_blocked_without_any_metadata_channel():
    service = AgentWorkflowService()
    plan = MetricQueryPlanner().plan("今天有效订单是多少", order_album())
    assert plan is not None
    before_mc = getattr(app_state, "_maxcompute_client", None)
    before_bff = getattr(app_state, "_bff_client", None)
    app_state._maxcompute_client = None
    app_state._bff_client = None
    try:
        with pytest.raises(QueryNeedsClarificationError) as raised:
            await service._validate_semantic_plan_metadata(plan)
        assert "未经结构核验" in raised.value.reason
    finally:
        app_state._maxcompute_client = before_mc
        app_state._bff_client = before_bff


def test_metric_rejects_same_table_from_wrong_album():
    context = order_album()[0]
    wrong_album = DataAlbumContext(
        album_id=999,
        name="其他专辑",
        tables=context.tables,
    )

    plan = MetricQueryPlanner().plan("今天有效订单是多少", [wrong_album])

    assert plan is not None
    assert plan.album_validation["status"] == "ungrounded"
    assert plan.albums == []


def test_metric_rejects_album_missing_reconciliation_asset():
    context = order_album()[0]
    incomplete_album = DataAlbumContext(
        album_id=888,
        name="订单",
        tables=[context.tables[0]],
    )

    plan = MetricQueryPlanner().plan("今天有效订单是多少", [incomplete_album])

    assert plan is not None
    assert plan.album_validation["status"] == "ungrounded"
    assert plan.album_validation["required_tables"][-1].endswith("tb_dwd_ord_gk_order_info_crt_df")

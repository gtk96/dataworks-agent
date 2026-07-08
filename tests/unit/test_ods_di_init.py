"""Phase 2 init/incremental + publish gate unit tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.services.ods_di import init_workflow
from dataworks_agent.services.ods_di.create_node import build_config
from dataworks_agent.services.ods_di.di_config import (
    build_copy_init_partition_sql,
    build_node_name,
    evaluate_publish_gate,
    partition_where_clause,
    replace_reader_where,
)


class TestBuildNodeName:
    def test_init_suffix(self) -> None:
        assert (
            build_node_name("ods_hl_shop__orders_hour", "init") == "ods_hl_shop__orders_hour_init"
        )

    def test_incremental_uses_table_name(self) -> None:
        assert (
            build_node_name("ods_hl_shop__orders_hour", "incremental") == "ods_hl_shop__orders_hour"
        )


class TestPartitionWhere:
    @pytest.mark.parametrize(
        ("granularity", "expected"),
        [
            ("hour", "dt='20170101' AND ht='00'"),
            ("hourly", "dt='20170101' AND ht='00'"),
            ("day", "dt='20170101'"),
            ("all", "dt='20170101'"),
        ],
    )
    def test_partition_where_clause(self, granularity: str, expected: str) -> None:
        assert partition_where_clause(granularity) == expected


class TestCopyInitPartitionSql:
    def test_hour_copy_sql(self) -> None:
        sql = build_copy_init_partition_sql(
            ods_table_name="ods_hl_shop__orders_hour",
            columns=["id", "name", "dt", "ht"],
            granularity="hour",
            dev_project="dataworks_dev",
            prod_project="dataworks",
        )
        assert "INSERT OVERWRITE TABLE dataworks.ods_hl_shop__orders_hour" in sql
        assert "PARTITION (dt='20170101', ht='00')" in sql
        assert "FROM dataworks_dev.ods_hl_shop__orders_hour" in sql
        assert "id" in sql
        assert "name" in sql
        assert "dt" not in sql.split("SELECT")[1].split("FROM")[0]

    def test_day_copy_sql(self) -> None:
        sql = build_copy_init_partition_sql(
            ods_table_name="ods_hl_shop__orders_day",
            columns=["id"],
            granularity="day",
        )
        assert "PARTITION (dt='20170101')" in sql
        assert "ht" not in sql


class TestPublishGate:
    def test_all_passed(self) -> None:
        gate = evaluate_publish_gate(
            tables_created=True,
            init_run_succeeded=True,
            dev_validated=True,
            prod_copy_succeeded=True,
            prod_validated=True,
            incremental_filter_valid=True,
        )
        assert gate["allowed"] is True
        assert gate["unmet_conditions"] == []

    def test_blocks_on_init_failure(self) -> None:
        gate = evaluate_publish_gate(
            tables_created=True,
            init_run_succeeded=False,
            dev_validated=True,
            prod_copy_succeeded=True,
            prod_validated=True,
            incremental_filter_valid=True,
        )
        assert gate["allowed"] is False
        assert "init_run_failed" in gate["unmet_conditions"]

    def test_blocks_on_row_count_mismatch_via_validation(self) -> None:
        gate = evaluate_publish_gate(
            tables_created=True,
            init_run_succeeded=True,
            dev_validated=True,
            prod_copy_succeeded=True,
            prod_validated=False,
            incremental_filter_valid=True,
        )
        assert gate["allowed"] is False
        assert "prod_not_validated" in gate["unmet_conditions"]


class TestBuildConfigTaskRole:
    def test_init_has_no_schedule(self) -> None:
        cfg = build_config(
            datasource_name="shop",
            source_table="orders",
            target_table="ods_hl_shop__orders_hour",
            columns=["id"],
            granularity="hour",
            split_pk="id",
            where_field="update_time",
            where_type="unix",
            source_step_type="hologres",
            task_role="init",
        )
        assert cfg["scheduled"] is False
        assert cfg["cron"] == ""
        assert cfg["di_config"]["steps"][0]["parameter"]["where"] == ""

    def test_incremental_has_schedule(self) -> None:
        cfg = build_config(
            datasource_name="shop",
            source_table="orders",
            target_table="ods_hl_shop__orders_hour",
            columns=["id"],
            granularity="hour",
            split_pk="id",
            where_field="update_time",
            where_type="unix",
            source_step_type="hologres",
            task_role="incremental",
        )
        assert cfg["scheduled"] is True
        assert cfg["cron"]


class TestReplaceReaderWhere:
    def test_replaces_where(self) -> None:
        cfg = build_config(
            datasource_name="shop",
            source_table="orders",
            target_table="ods_hl_shop__orders_hour",
            columns=["id", "update_time"],
            granularity="hour",
            split_pk="id",
            where_field="update_time",
            where_type="unix",
            source_step_type="mysql",
        )["di_config"]
        updated = replace_reader_where(cfg, "update_time >= 1")
        assert updated["steps"][0]["parameter"]["where"] == "update_time >= 1"


class TestTargetTablePassthrough:
    """Bug 2: init 流程必须尊重调用方传入的 target_table，而非静默重算。"""

    async def test_init_flow_honors_explicit_target_table(self, monkeypatch) -> None:
        captured: dict = {}

        async def fake_run_four_phases(bff, mcp, **kwargs):
            captured.update(kwargs)
            return {"success": True, "steps": {"create_node": {"uuid": "u"}}, "standard_ddl": ""}

        monkeypatch.setattr(init_workflow, "run_four_phases", fake_run_four_phases)
        monkeypatch.setattr(init_workflow, "ensure_table", AsyncMock(return_value={"status": "exists"}))
        monkeypatch.setattr(init_workflow, "infer_fields", AsyncMock(return_value={"status": "ok", "columns": ["id"]}))
        monkeypatch.setattr(init_workflow, "manual_run_init_node", AsyncMock(return_value=True))
        monkeypatch.setattr(init_workflow, "validate_init_partition", AsyncMock(return_value={"passed": True, "target_row_count": 1}))
        monkeypatch.setattr(init_workflow, "query_partition_count", AsyncMock(return_value=(True, 1)))
        bff = AsyncMock()
        bff.execute_sql_ida = AsyncMock(return_value="job")
        bff.wait_ida_job = AsyncMock(return_value=True)
        bff.deploy_nodes = AsyncMock(return_value=True)

        await init_workflow.run_with_initialization(
            bff,
            AsyncMock(),
            datasource_name="shop",
            source_table="orders",
            granularity="hour",
            target_table="custom_ods_name_hour",
        )
        assert captured["ods_table"] == "custom_ods_name_hour"

    async def test_init_flow_falls_back_to_generated_name(self, monkeypatch) -> None:
        captured: dict = {}

        async def fake_run_four_phases(bff, mcp, **kwargs):
            captured.update(kwargs)
            return {"success": True, "steps": {"create_node": {"uuid": "u"}}, "standard_ddl": ""}

        monkeypatch.setattr(init_workflow, "run_four_phases", fake_run_four_phases)
        monkeypatch.setattr(init_workflow, "ensure_table", AsyncMock(return_value={"status": "exists"}))
        monkeypatch.setattr(init_workflow, "infer_fields", AsyncMock(return_value={"status": "ok", "columns": ["id"]}))
        monkeypatch.setattr(init_workflow, "manual_run_init_node", AsyncMock(return_value=True))
        monkeypatch.setattr(init_workflow, "validate_init_partition", AsyncMock(return_value={"passed": True, "target_row_count": 1}))
        monkeypatch.setattr(init_workflow, "query_partition_count", AsyncMock(return_value=(True, 1)))
        bff = AsyncMock()
        bff.execute_sql_ida = AsyncMock(return_value="job")
        bff.wait_ida_job = AsyncMock(return_value=True)
        bff.deploy_nodes = AsyncMock(return_value=True)

        await init_workflow.run_with_initialization(
            bff,
            AsyncMock(),
            datasource_name="shop",
            source_table="orders",
            granularity="hour",
        )
        assert captured["ods_table"] == "ods_hl_shop__orders_hour"


class TestFirstIncrementalLookback:
    """首跑增量 lookback 兜底：改写 incremental 节点首跑 Reader.where。"""

    async def test_rewrites_reader_where_with_lookback(self) -> None:
        bff = AsyncMock()
        bff.update_node = AsyncMock(return_value=True)
        di_config = {
            "steps": [
                {"category": "reader", "parameter": {"where": "${bizdate} window"}},
                {"category": "processor"},
                {"category": "writer"},
            ]
        }
        res = await init_workflow.apply_first_incremental_lookback(
            bff,
            incr_uuid="u1",
            di_config=di_config,
            where_field="update_time",
            where_type="datetime",
            granularity="day",
            lookback_hours=12,
        )
        assert res["status"] == "ok"
        # update_node 被调用且写入的 where 含 lookback 表达式
        assert bff.update_node.await_count == 1
        written = json.loads(bff.update_node.call_args.args[1])
        assert "from_unixtime(unix_timestamp(" in written["steps"][0]["parameter"]["where"]
        assert "update_time >=" in written["steps"][0]["parameter"]["where"]

    async def test_skips_when_no_where_field(self) -> None:
        bff = AsyncMock()
        bff.update_node = AsyncMock(return_value=True)
        res = await init_workflow.apply_first_incremental_lookback(
            bff,
            incr_uuid="u1",
            di_config={"steps": [{"category": "reader", "parameter": {}}]},
            where_field="",
            where_type="none",
            granularity="day",
            lookback_hours=12,
        )
        assert res["status"] == "skipped"
        bff.update_node.assert_not_called()

    async def test_fails_on_nonpositive_lookback(self) -> None:
        bff = AsyncMock()
        bff.update_node = AsyncMock(return_value=True)
        res = await init_workflow.apply_first_incremental_lookback(
            bff,
            incr_uuid="u1",
            di_config={"steps": [{"category": "reader", "parameter": {}}]},
            where_field="update_time",
            where_type="datetime",
            granularity="day",
            lookback_hours=0,
        )
        assert res["status"] == "failed"
        bff.update_node.assert_not_called()

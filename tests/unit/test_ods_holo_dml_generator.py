"""Unit tests for ODS Holo DML generator."""

from __future__ import annotations

import pytest

from dataworks_agent.services.ods_holo.dml_generator import (
    OdsMetadataMissingError,
    _partition_literals,
    _render_dml,
    _resolve_where_clause,
    build_holo_ods_dml,
)


class TestHoloOdsWhereClause:
    def test_hour_uses_gmt_modify_create_coalesce(self) -> None:
        cols = [
            {"column_name": "gmt_modify", "data_type": "timestamp"},
            {"column_name": "gmt_create", "data_type": "timestamp"},
        ]
        clause = _resolve_where_clause(cols, "hour")
        assert "coalesce(gmt_modify, gmt_create)" in clause
        assert "${hour_last2h}" in clause
        assert "Asia/Shanghai" in clause

    def test_oms_style_update_create_coalesce(self) -> None:
        cols = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]
        clause = _resolve_where_clause(cols, "hour", "coalesce")
        assert "coalesce(update_time, create_time)" in clause

    def test_oms_style_update_create_or(self) -> None:
        cols = [
            {"column_name": "update_time", "data_type": "string"},
            {"column_name": "create_time", "data_type": "string"},
        ]
        clause = _resolve_where_clause(cols, "hour", "or")
        assert "update_time::timestamp >=" in clause
        assert " or create_time::timestamp >=" in clause

    def test_create_time_only(self) -> None:
        cols = [{"column_name": "create_time", "data_type": "string"}]
        clause = _resolve_where_clause(cols, "hour")
        assert "create_time" in clause
        assert "coalesce" not in clause

    def test_up_time_only(self) -> None:
        cols = [{"column_name": "up_time", "data_type": "bigint"}]
        clause = _resolve_where_clause(cols, "hour")
        assert "up_time" in clause
        assert "unix_timestamp" in clause


class TestHoloOdsRender:
    def test_hour_dml_includes_update_ht_and_partitions(self) -> None:
        dml = _render_dml(
            holo_schema="ofc",
            source_table="s_order",
            target_table="ods_hl_ofc__s_order_hour",
            target_columns=["order_id", "update_ht", "dt", "ht"],
            source_meta={"order_id": "bigint"},
            granularity="hour",
            where_clause="where 1=1",
        )
        assert "insert into cda.ods_hl_ofc__s_order_hour" in dml
        assert "from ofc.s_order" in dml
        assert "'${gmtdate}${hour_last1h}' as update_ht" in dml
        assert "'${gmtdate}' as dt" in dml
        assert "'${hour_last1h}' as ht" in dml

    def test_timestamp_cast_to_text(self) -> None:
        dml = _render_dml(
            holo_schema="ofc",
            source_table="s_order",
            target_table="ods_hl_ofc__s_order_hour",
            target_columns=["gmt_create", "dt"],
            source_meta={"gmt_create": "timestamp"},
            granularity="day",
            where_clause="",
        )
        assert "gmt_create::text" in dml


class TestBuildHoloOdsDml:
    @pytest.mark.asyncio
    async def test_rejects_select_star_when_metadata_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _empty_columns(*_args: object, **_kwargs: object) -> tuple[list, list]:
            return [], []

        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.dml_generator._load_source_columns",
            _empty_columns,
        )
        with pytest.raises(OdsMetadataMissingError, match="禁止生成 select \\*"):
            await build_holo_ods_dml(
                bff=object(),
                mcp=object(),
                holo_schema="ofc",
                source_table="unknown_table",
                target_table="ods_hl_ofc__unknown_table_hour",
                granularity="hour",
            )


class TestPartitionLiterals:
    def test_hour_triplet(self) -> None:
        update_ht, _dt, ht = _partition_literals("hour")
        assert "hour_last1h" in update_ht
        assert ht != ""

    def test_day_only_dt(self) -> None:
        update_ht, dt, ht = _partition_literals("day")
        assert update_ht == ""
        assert ht == ""
        assert "bizdate" in dt

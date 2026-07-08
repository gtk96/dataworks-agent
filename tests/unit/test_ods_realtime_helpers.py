"""ODS Realtime helper tests."""

from __future__ import annotations

from dataworks_agent.services.ods_realtime.helpers import (
    extract_fields_from_select_dml,
    generate_insert_sql,
    match_delta_table,
    preprocess_realtime_task,
)


class TestExtractFields:
    def test_basic_select(self) -> None:
        dml = "SELECT id, name, dt FROM t WHERE 1=1"
        fields = extract_fields_from_select_dml(dml)
        assert fields == ["id", "name"]

    def test_strips_trailing_partition_columns(self) -> None:
        dml = "SELECT id, dt, ht FROM delta_table"
        fields = extract_fields_from_select_dml(dml)
        assert fields == ["id"]


class TestMatchDeltaTable:
    def test_match_found(self) -> None:
        rows = [{"dst_table": "shop_db__orders_delta"}]
        assert match_delta_table("shop_db", "orders", rows) == "shop_db__orders_delta"

    def test_no_match(self) -> None:
        assert match_delta_table("shop_db", "orders", []) is None


class TestPreprocess:
    def test_success(self) -> None:
        prep = preprocess_realtime_task(
            database_schema="shop_db",
            table_name="orders",
            sync_rows=[{"dst_table": "shop_db__orders_delta"}],
        )
        assert prep["success"] is True
        assert prep["ods_table_name"] == "ods_mc_shop_db__orders_hour"
        assert prep["delta_table"] == "shop_db__orders_delta"

    def test_failure_when_no_delta(self) -> None:
        prep = preprocess_realtime_task(
            database_schema="shop_db",
            table_name="orders",
            sync_rows=[],
        )
        assert prep["success"] is False


class TestGenerateInsertSql:
    def test_sql_template(self) -> None:
        sql = generate_insert_sql(
            "ods_mc_shop_db__orders_hour",
            "shop_db__orders_delta",
            ["id", "name"],
            "dataworks",
            "dataworks_dev",
        )
        assert "insert overwrite table dataworks.ods_mc_shop_db__orders_hour" in sql
        assert "from dataworks_dev.shop_db__orders_delta" in sql
        assert "dw_update_time" in sql

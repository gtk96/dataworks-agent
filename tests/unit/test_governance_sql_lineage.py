"""Governance SQL/DDL lineage parser tests."""

from __future__ import annotations

from dataworks_agent.governance.sql_lineage import (
    extract_source_tables,
    is_temp_table,
    parse_ddl_structure,
    parse_sql_lineage,
)


class TestSqlLineage:
    def test_extract_source_tables(self) -> None:
        sql = """
        INSERT OVERWRITE TABLE dwd_ord_sale_hour
        SELECT a.id
        FROM ods_ord_order_hour a
        JOIN dim_pub_shop_all b ON a.shop_id = b.shop_id
        """
        assert extract_source_tables(sql) == ["ods_ord_order_hour", "dim_pub_shop_all"]

    def test_parse_sql_lineage(self) -> None:
        result = parse_sql_lineage(
            "SELECT * FROM ods_ord_order_hour a LEFT JOIN dim_pub_shop_all b ON a.id=b.id"
        )
        assert result["parse_state"] == "ok"
        assert "ods_ord_order_hour" in result["source_tables"]

    def test_is_temp_table(self) -> None:
        assert is_temp_table("tmp_stage_table")
        assert not is_temp_table("dim_pub_shop_all")


class TestParseDdlStructure:
    def test_columns_and_partitions(self) -> None:
        ddl = """
        CREATE TABLE dwd_ord_sale_hour (
          order_id STRING COMMENT 'order id',
          amount DECIMAL(18,2)
        )
        PARTITIONED BY (dt STRING COMMENT 'date')
        """
        result = parse_ddl_structure(ddl)
        assert result["parse_state"] == "ok"
        assert {field["name"] for field in result["columns"]} == {"order_id", "amount"}
        assert result["partitions"][0]["name"] == "dt"

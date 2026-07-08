"""Unit tests for local ODS DDL template fallback."""

from __future__ import annotations

from pathlib import Path

from dataworks_agent.services.ods_holo.local_ddl_registry import (
    extract_create_table_ddl,
    find_local_ods_ddl,
    query_columns_from_local_template,
)


class TestLocalDdlRegistry:
    def test_extract_t_order_ad_from_order_fulfillment_file(self) -> None:
        ddl_path = Path(
            "E:/dw-modeling-template/sql/order-fulfillment/ods/ddl/ods_hl_oms__order_fulfillment_hour_ddl.sql"
        )
        if not ddl_path.is_file():
            return
        text = ddl_path.read_text(encoding="utf-8")
        block = extract_create_table_ddl(text, "ods_hl_oms__t_order_ad_hour")
        assert block is not None
        assert "order_sn" in block.lower()
        assert "opt_id" in block.lower()

    def test_query_columns_for_oms_t_order_ad(self) -> None:
        root = Path("E:/dw-modeling-template/sql")
        if not root.is_dir():
            return
        rows = query_columns_from_local_template("oms", "t_order_ad", "hour")
        assert rows is not None
        names = {r["column_name"].lower() for r in rows}
        assert "order_sn" in names
        assert "opt_id" in names
        assert "update_ht" not in names

    def test_find_local_ddl_returns_block(self) -> None:
        root = Path("E:/dw-modeling-template/sql")
        if not root.is_dir():
            return
        ddl = find_local_ods_ddl("oms", "t_order_ad", "hour", template_root=str(root))
        assert ddl is not None
        assert "create table" in ddl.lower()

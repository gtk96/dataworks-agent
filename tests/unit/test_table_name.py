"""Table name generation and validation (ported from data-development-design)."""

from __future__ import annotations

import pytest

from dataworks_agent.naming.table_name import (
    generate_node_path,
    generate_ods_di_table_name,
    generate_ods_realtime_table_name,
    is_valid_table_name,
    validate_table_name,
)


class TestGenerateOdsDiTableName:
    def test_basic_generation(self) -> None:
        result = generate_ods_di_table_name("jky_singleshop", "orders", "hour")
        assert result == "ods_ms_jky_singleshop__orders_hour"

    @pytest.mark.parametrize(
        ("source_type", "expected_prefix"),
        [
            ("mysql", "ms"),
            ("oss", "oss"),
            ("hologres", "hl"),
            ("maxcompute", "mc"),
            ("elasticsearch", "es"),
            ("ftp", "ftp"),
            ("mongodb", "mg"),
            ("polardb", "pl"),
        ],
    )
    def test_source_type_prefixes(self, source_type: str, expected_prefix: str) -> None:
        result = generate_ods_di_table_name(
            "gimp", "gk_gmall3_order", "hour", source_type=source_type
        )
        assert result == f"ods_{expected_prefix}_gimp__gk_gmall3_order_hour"

    def test_hologres_workspace_path(self) -> None:
        result = generate_ods_di_table_name(
            "ofc", "order_fulfillment", "hour", source_type="hologres"
        )
        assert result == "ods_hl_ofc__order_fulfillment_hour"


class TestGenerateOdsRealtimeTableName:
    def test_basic_generation(self) -> None:
        result = generate_ods_realtime_table_name("mydb", "orders", "hour")
        assert result == "ods_mc_mydb__orders_hour"


class TestGenerateNodePath:
    def test_basic_path(self) -> None:
        result = generate_node_path(
            "业务流程/001_公共域/数据集成/00_数据输入",
            "ods_ms_src__tbl_hour",
        )
        assert result == "业务流程/001_公共域/数据集成/00_数据输入/ods_ms_src__tbl_hour"


class TestValidateTableName:
    def test_valid_simple_name(self) -> None:
        assert validate_table_name("ods_ms_src__tbl_hour") == []

    def test_starts_with_digit(self) -> None:
        errors = validate_table_name("1table")
        assert any("数字开头" in e for e in errors)

    def test_empty_string(self) -> None:
        errors = validate_table_name("")
        assert len(errors) == 1
        assert "不能为空" in errors[0]


class TestIsValidTableName:
    def test_valid_name_returns_true(self) -> None:
        assert is_valid_table_name("ods_ms_src__tbl_hour") is True

    def test_too_long_returns_false(self) -> None:
        assert is_valid_table_name("a" * 129) is False


class TestGenerateAndValidate:
    def test_di_generated_name_is_valid(self) -> None:
        name = generate_ods_di_table_name("mysql_prod", "orders", "hour")
        assert is_valid_table_name(name) is True

    def test_di_name_with_long_components_may_fail_validation(self) -> None:
        long_ds = "a" * 60
        long_tbl = "b" * 60
        name = generate_ods_di_table_name(long_ds, long_tbl, "hour")
        assert is_valid_table_name(name) is False
        errors = validate_table_name(name)
        assert any("128" in e for e in errors)

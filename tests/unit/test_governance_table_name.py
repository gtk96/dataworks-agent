"""Governance table name parser tests."""

from __future__ import annotations

from dataworks_agent.governance.table_name_parser import (
    build_table_guid,
    identify_layer,
    identify_layer_ext,
    parse_table_name,
)


class TestIdentifyLayer:
    def test_dwd_prefix(self) -> None:
        assert identify_layer("dwd_ord_order_hour") == "DWD"

    def test_dmr_ext(self) -> None:
        assert identify_layer_ext("dmr_risk_order_day") == "DMR"
        assert identify_layer_ext("dma_fin_fee_day") == "DMR"


class TestParseTableName:
    def test_roundtrip(self) -> None:
        parsed = parse_table_name("dwd_ord_sale_detail_hour")
        assert parsed["layer"] == "DWD"
        assert parsed["subject_domain"] == "ORD"
        assert parsed["description"] == "sale_detail"
        assert parsed["update_mode"] == "hour"


class TestBuildTableGuid:
    def test_guid(self) -> None:
        assert (
            build_table_guid("dwd_ord_order_day", "dataworks") == "odps.dataworks.dwd_ord_order_day"
        )

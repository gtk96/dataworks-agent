"""DWD type resolver and metadata builder tests."""

from __future__ import annotations

import pytest

from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
from dataworks_agent.modeling.dwd.type_resolver import DwdTypeResolver


class TestDwdTypeResolver:
    def test_id_suffix_is_string(self) -> None:
        resolved = DwdTypeResolver().resolve("order_id")
        assert resolved.type == "string"
        assert resolved.category == "normal"

    def test_amount_keyword(self) -> None:
        resolved = DwdTypeResolver().resolve("pay_amount", "支付金额")
        assert resolved.type == "decimal(24,6)"
        assert resolved.category == "amount"

    def test_quantity_keyword(self) -> None:
        resolved = DwdTypeResolver().resolve("item_qty")
        assert resolved.type == "bigint"
        assert resolved.category == "quantity"


class TestBuildStructuredMetadata:
    def test_basic_payload(self) -> None:
        payload = {
            "sources": [
                {
                    "table_name": "dataworks.ods_ord_order_day",
                    "alias": "T1",
                    "is_master": True,
                }
            ],
            "targets": [
                {
                    "table_name": "dataworks_dev.dwd_ord_order_day",
                    "update_mode": "daily",
                    "partition_fields": ["dt"],
                    "logical_primary_keys": ["order_id"],
                    "fields": [{"name": "order_id", "type": "STRING"}],
                }
            ],
            "field_mappings": [
                {
                    "source_field_name": "order_id",
                    "target_field_name": "order_id",
                    "field_category": "normal",
                }
            ],
        }
        meta = build_structured_metadata(payload)
        assert meta.master_table.alias == "T1"
        assert meta.logical_primary_keys == ["order_id"]
        assert meta.field_mappings[0].source_alias == "T1"

    def test_empty_targets_raises(self) -> None:
        with pytest.raises(ValueError, match="targets"):
            build_structured_metadata({"sources": [{"table_name": "t", "alias": "T1"}]})

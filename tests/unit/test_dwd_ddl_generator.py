"""DWD DDL generator unit tests (ported from data-development-design)."""

from __future__ import annotations

import pytest

from dataworks_agent.modeling.dwd.ddl_generator import ColumnDef, DDLMetadata, DwdDDLGenerator


@pytest.fixture
def generator() -> DwdDDLGenerator:
    return DwdDDLGenerator()


def _sample_metadata(**overrides) -> DDLMetadata:
    base = {
        "target_table_name": "dataworks_dev.dwd_ord_order_day",
        "table_comment": "订单明细",
        "columns": [
            ColumnDef(name="order_id", type="STRING", comment="订单ID"),
            ColumnDef(name="pay_amt", type="DECIMAL(24,6)", comment="支付金额"),
        ],
        "partition_fields": [ColumnDef(name="dt", type="STRING", comment="分区")],
        "update_mode": "daily",
    }
    base.update(overrides)
    return DDLMetadata(**base)


class TestDwdDDLGenerator:
    def test_create_table_header(self, generator: DwdDDLGenerator) -> None:
        ddl = generator.generate(_sample_metadata())
        assert "drop table if exists dataworks_dev.dwd_ord_order_day" in ddl
        assert "create table dataworks_dev.dwd_ord_order_day" in ddl
        assert "if not exists" not in ddl.lower()

    def test_partition_and_no_lifecycle(self, generator: DwdDDLGenerator) -> None:
        ddl = generator.generate(_sample_metadata())
        assert "PARTITIONED BY (dt STRING" in ddl
        assert "LIFECYCLE" not in ddl

    def test_full_mode_permanent(self, generator: DwdDDLGenerator) -> None:
        ddl = generator.generate(_sample_metadata(update_mode="full"))
        assert "LIFECYCLE" not in ddl

    def test_from_structured_metadata(self, generator: DwdDDLGenerator) -> None:
        structured = {
            "targets": [
                {
                    "table_name": "dwd_ord_order_hour",
                    "table_comment": "订单小时表",
                    "update_mode": "hourly",
                    "partition_fields": ["dt", "ht"],
                    "fields": [
                        {"name": "order_id", "type": "STRING", "comment": "订单ID"},
                        {"name": "dt", "type": "STRING"},
                        {"name": "ht", "type": "STRING"},
                    ],
                }
            ]
        }
        meta = generator.from_structured_metadata(structured)
        ddl = generator.generate(meta)
        assert "dwd_ord_order_hour" in ddl
        assert "ht STRING" in ddl

    def test_empty_targets_raises(self, generator: DwdDDLGenerator) -> None:
        with pytest.raises(ValueError, match="at least one target"):
            generator.from_structured_metadata({"targets": []})

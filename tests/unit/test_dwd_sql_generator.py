"""DWD SQL generator unit tests (ported from data-development-design)."""

from __future__ import annotations

import pytest

from dataworks_agent.modeling.dwd.schemas import (
    FieldMappingInfo,
    JoinInfo,
    SourceInfo,
    StructuredMetadata,
)
from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator


@pytest.fixture
def generator() -> DwdSQLGenerator:
    return DwdSQLGenerator()


def _make_metadata(
    *,
    update_mode: str = "full",
    partition_fields: list[str] | None = None,
    logical_primary_keys: list[str] | None = None,
    field_mappings: list[FieldMappingInfo] | None = None,
    joins: list[JoinInfo] | None = None,
    target_table_name: str = "dwd_ord_order_day",
) -> StructuredMetadata:
    if partition_fields is None:
        partition_fields = ["dt"]
    if logical_primary_keys is None:
        logical_primary_keys = []
    if field_mappings is None:
        field_mappings = [
            FieldMappingInfo(
                source_alias="T1",
                source_field_name="order_id",
                target_field_name="order_id",
                field_category="normal",
            ),
        ]
    if joins is None:
        joins = []

    return StructuredMetadata(
        target_table_name=target_table_name,
        update_mode=update_mode,
        partition_fields=partition_fields,
        logical_primary_keys=logical_primary_keys,
        master_table=SourceInfo(table_name="ods_ord_order_day", alias="T1"),
        sources=[SourceInfo(table_name="ods_ord_order_day", alias="T1")],
        field_mappings=field_mappings,
        joins=joins,
    )


class TestCoalesceNullHandling:
    def test_normal_category_gets_coalesce(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(
            field_mappings=[
                FieldMappingInfo(
                    source_alias="T1",
                    source_field_name="user_name",
                    target_field_name="user_name",
                    field_category="normal",
                ),
            ],
        )
        sql = generator.generate(metadata)
        assert "COALESCE(T1.user_name, '-') AS user_name" in sql

    def test_amount_category_no_coalesce(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(
            field_mappings=[
                FieldMappingInfo(
                    source_alias="T1",
                    source_field_name="pay_amt",
                    target_field_name="pay_amt",
                    field_category="amount",
                ),
            ],
        )
        sql = generator.generate(metadata)
        assert "COALESCE" not in sql
        assert "T1.pay_amt AS pay_amt" in sql


class TestPartitionConditions:
    def test_daily_uses_bizdate(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(update_mode="daily", logical_primary_keys=["order_id"])
        sql = generator.generate(metadata)
        assert "${bizdate}" in sql
        assert "${pre_bizdate}" in sql

    def test_hourly_uses_gmtdate(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(
            update_mode="hourly",
            partition_fields=["dt", "ht"],
            logical_primary_keys=["order_id"],
            target_table_name="dwd_ord_order_hour",
        )
        sql = generator.generate(metadata)
        assert "${gmtdate}" in sql
        assert "${hour_last1h}" in sql
        assert "ALTER TABLE" in sql


class TestIncrementalMode:
    def test_incremental_has_union_all(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(update_mode="daily", logical_primary_keys=["order_id"])
        sql = generator.generate(metadata)
        assert "INSERT OVERWRITE TABLE" in sql
        assert "UNION ALL" in sql
        assert "LEFT ANTI JOIN" in sql

    def test_missing_pk_raises(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(update_mode="daily", logical_primary_keys=[])
        with pytest.raises(ValueError, match="logical_primary_keys"):
            generator.generate(metadata)


class TestJoinSupport:
    def test_join_in_full_mode(self, generator: DwdSQLGenerator) -> None:
        metadata = _make_metadata(
            joins=[
                JoinInfo(
                    join_type="LEFT",
                    right_table_name="ods_ord_item_day",
                    right_alias="T2",
                    on_condition="T1.order_id = T2.order_id",
                )
            ],
        )
        sql = generator.generate(metadata)
        assert "LEFT JOIN ods_ord_item_day T2" in sql

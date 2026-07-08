"""ODS DI pure logic tests (ported from data-development-design)."""

from __future__ import annotations

import json

import pytest

from dataworks_agent.services.ods_di.di_config import (
    build_business_partition,
    build_di_task_config,
    build_init_partition,
    build_where_clause,
    compare_ddl_structures,
    infer_split_pk,
    inject_schema_prefix_in_ddl,
)
from dataworks_agent.services.ods_di.where_infer import (
    infer_where_field,
)


class TestInferSplitPk:
    def test_primary_key(self) -> None:
        columns = [
            {"column_name": "id", "data_type": "bigint", "column_key": "PRI"},
            {"column_name": "name", "data_type": "varchar", "column_key": ""},
        ]
        assert infer_split_pk(columns, "orders") == "id"

    def test_fallback_id(self) -> None:
        columns = [{"column_name": "id", "data_type": "bigint", "column_key": ""}]
        assert infer_split_pk(columns, "orders") == "id"


class TestInferWhereField:
    def test_datetime_candidate(self) -> None:
        columns = [{"column_name": "update_time", "data_type": "datetime", "column_key": ""}]
        assert infer_where_field(columns) == {
            "where_field": "update_time",
            "where_type": "datetime",
        }

    def test_unix_candidate(self) -> None:
        columns = [{"column_name": "gmt_modified", "data_type": "bigint", "column_key": ""}]
        assert infer_where_field(columns) == {
            "where_field": "gmt_modified",
            "where_type": "unix",
        }


class TestBuildWhereClause:
    def test_hour_unix(self) -> None:
        clause = build_where_clause("unix", "update_time", "hour")
        assert "unix_timestamp" in clause
        assert "gmtdate_last2h" in clause

    def test_day_datetime(self) -> None:
        clause = build_where_clause("datetime", "updated_at", "day")
        assert "bizdate" in clause


class TestBuildDiTaskConfig:
    def test_hour_granularity_config(self) -> None:
        config = build_di_task_config(
            datasource_name="mydb",
            source_table_name="orders",
            ods_table_name="ods_ms_mydb__orders_hour",
            columns=["id", "name", "update_time"],
            odps_datasource_name="dataworks_dev",
            granularity="hour",
            split_pk="id",
            where_type="unix",
            where_field="update_time",
        )
        reader = config["steps"][0]
        writer = config["steps"][2]
        assert reader["stepType"] == "mysql"
        assert "unix_timestamp" in reader["parameter"]["where"]
        assert writer["parameter"]["partition"] == "dt=${gmtdate},ht=${hour_last1h}"
        assert config["extend"]["mode"] == "wizard"

    def test_init_config_has_no_where(self) -> None:
        config = build_di_task_config(
            datasource_name="mydb",
            source_table_name="orders",
            ods_table_name="ods_ms_mydb__orders_hour",
            columns=["id"],
            odps_datasource_name="dataworks_dev",
            granularity="hour",
            where_type="datetime",
            where_field="update_time",
            task_role="init",
        )
        assert config["steps"][0]["parameter"]["where"] == ""
        assert config["steps"][2]["parameter"]["partition"] == "dt=20170101,ht=00"

    def test_json_serializable(self) -> None:
        config = build_di_task_config(
            datasource_name="ds",
            source_table_name="t",
            ods_table_name="ods_ms_ds__t_hour",
            columns=["a"],
            odps_datasource_name="dataworks",
        )
        parsed = json.loads(json.dumps(config, ensure_ascii=False))
        assert parsed["type"] == "job"


class TestDdlHelpers:
    def test_inject_schema_prefix(self) -> None:
        ddl = "CREATE TABLE ods_ms_shop__orders_hour (id BIGINT);"
        assert inject_schema_prefix_in_ddl(ddl, "dataworks_dev").startswith(
            "CREATE TABLE dataworks_dev.ods_ms_shop__orders_hour"
        )

    def test_compare_compatible(self) -> None:
        expected = (
            "CREATE TABLE expected (id BIGINT, name STRING) PARTITIONED BY (dt STRING, ht STRING)"
        )
        actual = "CREATE TABLE dataworks.actual (id BIGINT, name STRING) PARTITIONED BY (dt STRING, ht STRING)"
        result = compare_ddl_structures(expected, actual)
        assert result["compatible"] is True
        assert result["differences"] == []


class TestPartitions:
    def test_business_hour_partition(self) -> None:
        assert build_business_partition("hour") == "dt=${gmtdate},ht=${hour_last1h}"

    def test_init_hour_partition(self) -> None:
        assert build_init_partition("hour") == "dt=20170101,ht=00"

    @pytest.mark.parametrize("granularity", ["hour", "hourly", "day", "all"])
    def test_business_never_uses_init_date(self, granularity: str) -> None:
        assert "20170101" not in build_business_partition(granularity)

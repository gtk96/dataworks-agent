"""ODS OSS pure logic tests (ported from data-development-design)."""

from __future__ import annotations

from dataworks_agent.services.ods_oss.config import (
    OSS_DEFAULT_DEPENDENCIES,
    SUPPORTED_FILE_FORMATS,
    build_oss_import_sql,
    parse_oss_path,
    validate_oss_config,
)


class TestParseOssPath:
    def test_full_oss_uri(self) -> None:
        result = parse_oss_path("oss://my-bucket/data/input/")
        assert result["bucket"] == "my-bucket"
        assert result["object_key"] == "data/input"

    def test_bucket_only(self) -> None:
        result = parse_oss_path("oss://my-bucket")
        assert result["bucket"] == "my-bucket"
        assert result["object_key"] == ""


class TestValidateOssConfig:
    def test_valid_config(self) -> None:
        errors = validate_oss_config("oss://bucket/path/", "ods_oss_test_day", "csv")
        assert errors == []

    def test_multiple_errors(self) -> None:
        errors = validate_oss_config("", "", "xml")
        assert len(errors) == 3


class TestBuildOssImportSql:
    def test_day_schedule_partition(self) -> None:
        sql = build_oss_import_sql(
            target_table="ods_oss_test_day",
            oss_path="oss://bucket/data/",
            file_format="csv",
            schedule_type="day",
        )
        assert "dt='${bizdate}'" in sql
        assert "LOAD OVERWRITE TABLE" in sql

    def test_hour_schedule_partition(self) -> None:
        sql = build_oss_import_sql(
            target_table="ods_oss_test_hour",
            oss_path="oss://bucket/data/",
            file_format="csv",
            schedule_type="hour",
        )
        assert "dt='${gmtdate}'" in sql
        assert "ht='${hour_last1h}'" in sql

    def test_wildcard_appended(self) -> None:
        sql = build_oss_import_sql(
            target_table="table",
            oss_path="oss://bucket/data/",
            file_format="csv",
            wildcard="*.csv",
        )
        assert "oss://bucket/data/*.csv" in sql


class TestConstants:
    def test_supported_formats(self) -> None:
        assert {"csv", "json", "parquet"} == SUPPORTED_FILE_FORMATS

    def test_default_dependencies(self) -> None:
        assert OSS_DEFAULT_DEPENDENCIES[0]["type"] == "CrossCycleDependsOnSelf"

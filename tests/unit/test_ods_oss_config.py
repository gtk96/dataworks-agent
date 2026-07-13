"""ODS OSS pure logic tests (ported from data-development-design)."""

from __future__ import annotations

import pytest

from dataworks_agent.services.ods_oss.config import (
    OSS_DEFAULT_DEPENDENCIES,
    SUPPORTED_FILE_FORMATS,
    build_oss_import_sql,
    infer_file_format,
    normalize_file_format,
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

    def test_endpoint_style_uri_is_normalized(self) -> None:
        result = parse_oss_path(
            "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/ads/data/report/"
        )
        assert result["endpoint"] == "oss-cn-shenzhen-internal.aliyuncs.com"
        assert result["bucket"] == "example-data-bucket"
        assert result["object_key"] == "ads/data/report"
        assert result["is_prefix"] is True
        assert result["canonical_uri"] == "oss://example-data-bucket/ads/data/report/"

    def test_rejects_spoofed_aliyuncs_endpoint(self) -> None:
        with pytest.raises(ValueError, match="endpoint"):
            parse_oss_path("oss://oss-cn-test.aliyuncs.com.evil.example/bucket/path/")

    def test_rejects_control_characters_in_object_key(self) -> None:
        with pytest.raises(ValueError, match="\u63a7\u5236\u5b57\u7b26"):
            parse_oss_path("oss://bucket/path\nunsafe/")


class TestFileFormat:
    def test_normalize_json_lines_aliases(self) -> None:
        assert normalize_file_format("JSON Lines") == "json"
        assert normalize_file_format("jsonl") == "json"

    def test_infer_format_from_object_suffix(self) -> None:
        assert infer_file_format("oss://bucket/path/data.ndjson") == "json"
        assert infer_file_format("oss://bucket/path/data.parquet") == "parquet"


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

    def test_endpoint_style_path_is_canonicalized(self) -> None:
        sql = build_oss_import_sql(
            target_table="ods_oss_test_day",
            oss_path=(
                "oss://oss-cn-shenzhen-internal.aliyuncs.com/"
                "example-data-bucket/ads/data/report/"
            ),
            file_format="json",
        )
        assert "oss://example-data-bucket/ads/data/report" in sql
        assert "oss-cn-shenzhen-internal.aliyuncs.com" not in sql

    def test_oss_path_quote_is_escaped_in_sql_literal(self) -> None:
        sql = build_oss_import_sql(
            target_table="ods_oss_test_day",
            oss_path="oss://bucket/data/o'reilly/",
            file_format="json",
        )
        assert "FROM LOCATION 'oss://bucket/data/o''reilly'" in sql

    def test_rejects_wildcard_control_characters(self) -> None:
        with pytest.raises(ValueError, match="wildcard"):
            build_oss_import_sql(
                target_table="ods_oss_test_day",
                oss_path="oss://bucket/data/",
                file_format="json",
                wildcard="*.json\nDROP TABLE x",
            )


class TestConstants:
    def test_supported_formats(self) -> None:
        assert {"csv", "json", "parquet"} == SUPPORTED_FILE_FORMATS

    def test_default_dependencies(self) -> None:
        assert OSS_DEFAULT_DEPENDENCIES[0]["type"] == "CrossCycleDependsOnSelf"

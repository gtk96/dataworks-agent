from __future__ import annotations

import pytest

from dataworks_agent.services.ods_oss.config import (
    OSS_DEFAULT_DEPENDENCIES,
    SUPPORTED_FILE_FORMATS,
    build_ods_extract_sql,
    infer_file_format,
    normalize_file_format,
    ods_table_name,
    parse_oss_path,
    validate_oss_config,
)


def test_parse_full_oss_uri() -> None:
    result = parse_oss_path("oss://my-bucket/data/input/")
    assert result["bucket"] == "my-bucket"
    assert result["object_key"] == "data/input"


def test_parse_endpoint_style_uri() -> None:
    result = parse_oss_path(
        "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/ads/data/report/"
    )
    assert result["endpoint"] == "oss-cn-shenzhen-internal.aliyuncs.com"
    assert result["bucket"] == "example-data-bucket"
    assert result["object_key"] == "ads/data/report"
    assert result["is_prefix"] is True


def test_parse_rejects_spoofed_endpoint_and_controls() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        parse_oss_path("oss://oss-cn-test.aliyuncs.com.evil.example/bucket/path/")
    with pytest.raises(ValueError, match="控制字符"):
        parse_oss_path("oss://bucket/path\nunsafe/")


def test_format_aliases_and_inference() -> None:
    assert normalize_file_format("JSON Lines") == "json"
    assert normalize_file_format("jsonl") == "json"
    assert infer_file_format("oss://bucket/path/data.ndjson") == "json"
    assert infer_file_format("oss://bucket/path/data.parquet") == "parquet"


def test_validate_config() -> None:
    assert validate_oss_config("oss://bucket/path/", "ods_oss_test_day", "csv") == []
    assert len(validate_oss_config("", "", "xml")) == 3


def test_ods_names_follow_granularity() -> None:
    assert ods_table_name("tiktok_ad_struct", "day") == "ods_mc_ads_data__tiktok_ad_struct_day"
    assert ods_table_name("tiktok_ad_insights", "hour") == "ods_mc_ads_data__tiktok_ad_insights_hour"


def test_daily_ods_sql_uses_bizdate() -> None:
    sql = build_ods_extract_sql(
        source_table="tiktok_ad_struct",
        target_table="ods_mc_ads_data__tiktok_ad_struct_day",
        granularity="day",
        source_partition_value="20260713",
    )
    assert "ALTER TABLE giikin.ods_mc_ads_data__tiktok_ad_struct_day" in sql
    assert "ADD IF NOT EXISTS PARTITION (dt='${bizdate}')" in sql
    assert "INSERT OVERWRITE TABLE giikin.ods_mc_ads_data__tiktok_ad_struct_day" in sql
    assert "FROM giikin_develop.tiktok_ad_struct" in sql
    assert "ht=" not in sql and "${gmtdate}" not in sql
    assert "LOAD " + "OVERWRITE" not in sql
    assert "FROM " + "LOCATION" not in sql


def test_hourly_ods_sql_precreates_before_insert() -> None:
    sql = build_ods_extract_sql(
        source_table="tiktok_ad_insights",
        target_table="ods_mc_ads_data__tiktok_ad_insights_hour",
        granularity="hour",
        source_partition_value="2026071412",
    )
    assert sql.index("ADD IF NOT EXISTS PARTITION") < sql.index("INSERT OVERWRITE")
    assert "dt='${gmtdate}', ht='${hour_last1h}'" in sql
    assert "FROM giikin_develop.tiktok_ad_insights" in sql


def test_partition_value_is_required() -> None:
    with pytest.raises(ValueError, match="source_partition_value"):
        build_ods_extract_sql(
            source_table="source",
            target_table="ods_mc_ads_data__source_hour",
            granularity="hour",
            source_partition_value=None,
        )


def test_partition_value_is_escaped() -> None:
    sql = build_ods_extract_sql(
        source_table="source",
        target_table="ods_mc_ads_data__source_day",
        granularity="day",
        source_partition_value="2026'0713",
    )
    assert "2026''0713" in sql


def test_supported_formats_and_dependencies() -> None:
    assert {"csv", "json", "parquet"} == SUPPORTED_FILE_FORMATS
    assert OSS_DEFAULT_DEPENDENCIES[0]["type"] == "CrossCycleDependsOnSelf"

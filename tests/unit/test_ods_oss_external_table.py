from __future__ import annotations

from dataworks_agent.services.ods_oss.external_table import (
    ExternalTableSpec,
    build_external_table_ddl,
    source_name_from_location,
    validate_external_table_compatibility,
)


def test_source_name_from_prefix():
    assert source_name_from_location({"object_key": "ads/report", "is_prefix": True}) == "report"


def test_build_external_table_ddl():
    ddl = build_external_table_ddl(
        ExternalTableSpec(
            project="giikin_develop",
            table="report",
            columns=(("json_data", "STRING"),),
            partition_columns=("pt",),
            file_format="json",
            location="oss://bucket/ads/report/",
        )
    )
    assert ddl.startswith("CREATE EXTERNAL TABLE IF NOT EXISTS giikin_develop.report")
    assert "PARTITIONED BY (`pt` STRING)" in ddl
    assert "STORED AS TEXTFILE" in ddl
    assert "LOCATION 'oss://bucket/ads/report'" in ddl


def test_incompatible_external_table_is_rejected():
    spec = ExternalTableSpec(
        project="giikin_develop",
        table="report",
        columns=(("json_data", "STRING"),),
        partition_columns=("pt",),
        file_format="json",
        location="oss://bucket/ads/report/",
    )
    errors = validate_external_table_compatibility(
        spec,
        {
            "project": "giikin_develop",
            "table_name": "report",
            "location": "oss://bucket/other/",
            "columns": [{"name": "json_data", "type": "STRING"}],
            "partition_columns": ["pt"],
        },
    )
    assert "external table LOCATION mismatch" in errors

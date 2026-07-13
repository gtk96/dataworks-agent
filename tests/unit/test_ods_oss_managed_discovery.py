from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from dataworks_agent.services.ods_oss import managed_discovery

OSS_PATH = "oss://oss-cn-shenzhen-internal.aliyuncs.com/example-data-bucket/ads/data/report/"


class FakeBff:
    def __init__(self, *, bucket: str = "example-data-bucket", table_name: str = "report") -> None:
        self.list_datasources = AsyncMock(
            return_value=[
                {
                    "name": "managed_oss",
                    "type": "oss",
                    "connectionProperties": {"bucket": bucket},
                }
            ]
        )
        self.search_tables = AsyncMock(
            return_value=[
                {
                    "table_name": table_name,
                    "entity_guid": "odps.dev.report",
                }
            ]
        )
        self.get_creation_ddl = AsyncMock(
            return_value=(
                "create external table dev.report (json_data string) "
                "stored as textfile "
                "location 'oss://oss-cn-shenzhen-internal.aliyuncs.com/"
                "example-data-bucket/ads/data/report/'"
            )
        )


@pytest.mark.asyncio
async def test_managed_discovery_uses_exact_datasource_table_and_location() -> None:
    bff = FakeBff()

    result = await managed_discovery.discover_managed_oss_schema(bff, OSS_PATH, "json")

    assert result == {
        "success": True,
        "channel": "dataworks_managed_datasource",
        "source": "dataworks_managed_datasource",
        "location": {
            "endpoint": "oss-cn-shenzhen-internal.aliyuncs.com",
            "bucket": "example-data-bucket",
            "object_key": "ads/data/report",
            "is_prefix": True,
            "canonical_uri": "oss://example-data-bucket/ads/data/report/",
        },
        "datasource_name": "managed_oss",
        "metadata_source": "registered_external_table",
        "file_format": "json",
        "record_count": 0,
        "columns": [{"name": "json_data", "type": "STRING", "comment": ""}],
        "ingestion_mode": "raw_json_text",
    }
    bff.search_tables.assert_awaited_once_with("report", page_size=50)


@pytest.mark.asyncio
async def test_managed_discovery_rejects_near_bucket_and_table_matches() -> None:
    bff = FakeBff(bucket="example-data-bucket-archive", table_name="report_backup")

    result = await managed_discovery.discover_managed_oss_schema(bff, OSS_PATH, "json")

    assert result["success"] is False
    assert result["error_code"] == "managed_datasource_not_found"
    bff.search_tables.assert_not_awaited()
    assert "connectionProperties" not in result


@pytest.mark.asyncio
async def test_managed_success_does_not_call_local_oss_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    bff = FakeBff()
    local = AsyncMock()
    monkeypatch.setattr(managed_discovery.asyncio, "to_thread", local)

    result = await managed_discovery.discover_oss_schema_with_fallback(bff, OSS_PATH, "json")

    assert result["success"] is True
    assert result["channel"] == "dataworks_managed_datasource"
    local.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_channels_fail_return_safe_actionable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bff = FakeBff(bucket="other-bucket")
    monkeypatch.setattr(
        managed_discovery,
        "discover_oss_schema",
        lambda *_: {
            "success": False,
            "location": {"bucket": "example-data-bucket", "object_key": "ads/data/report"},
            "file_format": "json",
            "error_code": "accessdenied",
            "error": "AccessDenied with private detail",
            "attempted_endpoints": ["oss-cn-shenzhen.aliyuncs.com"],
        },
    )

    result = await managed_discovery.discover_oss_schema_with_fallback(bff, OSS_PATH, "json")

    assert result["success"] is False
    assert result["error_code"] == "schema_discovery_unavailable"
    assert result["attempts"][-1]["error_code"] == "accessdenied"
    assert "AccessDenied" not in result["error"]
    assert "connectionProperties" not in result
    assert "sample_content" not in result

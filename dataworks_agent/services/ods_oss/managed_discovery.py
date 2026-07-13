"""Discover OSS schema through DataWorks managed metadata before local SDK access."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import PurePosixPath
from typing import Any

from dataworks_agent.governance.sql_lineage import parse_ddl_structure
from dataworks_agent.services.ods_oss.config import infer_file_format, parse_oss_path
from dataworks_agent.services.ods_oss.schema_discovery import discover_oss_schema

logger = logging.getLogger(__name__)

_LOCATION_RE = re.compile(r"\bLOCATION\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SAFE_SOURCE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RAW_JSON_COLUMN_NAMES = {"json", "json_data", "raw", "raw_data", "raw_json", "value", "content", "line"}


def _nested_exact_value(value: Any, needle: str) -> bool:
    """Match a datasource property exactly without substring-based bucket guesses."""
    if isinstance(value, dict):
        return any(_nested_exact_value(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_nested_exact_value(item, needle) for item in value)
    return isinstance(value, (str, int)) and str(value).strip() == needle


def _datasource_name(source: dict[str, Any]) -> str:
    for key in ("name", "dataSourceName", "datasourceName", "displayName"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in source.values():
        if isinstance(value, dict):
            nested = _datasource_name(value)
            if nested:
                return nested
    return ""


def _datasource_type(source: dict[str, Any]) -> str:
    for key in ("type", "datasourceType", "dataSourceType"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _source_name(location: dict[str, Any]) -> str:
    object_key = str(location.get("object_key") or "").rstrip("/")
    if not object_key:
        return ""
    name = PurePosixPath(object_key).name
    if not location.get("is_prefix") and "." in name:
        name = name.rsplit(".", 1)[0]
    return name if _SAFE_SOURCE_NAME.fullmatch(name) else ""


def _ddl_location_matches(ddl: str, expected: dict[str, Any]) -> bool:
    match = _LOCATION_RE.search(ddl)
    if not match:
        return False
    try:
        actual = parse_oss_path(match.group(1))
    except ValueError:
        return False
    return (
        str(actual.get("bucket") or "").casefold()
        == str(expected.get("bucket") or "").casefold()
        and str(actual.get("object_key") or "").strip("/")
        == str(expected.get("object_key") or "").strip("/")
    )


def _raw_json_text_mode(ddl: str, columns: list[dict[str, Any]], file_format: str) -> bool:
    if file_format != "json" or len(columns) != 1 or "stored as textfile" not in ddl.lower():
        return False
    column = columns[0]
    name = str(column.get("name") or "").strip().lower()
    data_type = str(column.get("type") or "").strip().lower()
    return name in _RAW_JSON_COLUMN_NAMES and data_type in {"string", "varchar", "text"}


def _managed_failure(
    location: dict[str, Any], file_format: str, error_code: str
) -> dict[str, Any]:
    return {
        "success": False,
        "channel": "dataworks_managed_datasource",
        "source": "dataworks_managed_datasource",
        "location": location,
        "file_format": file_format,
        "error_code": error_code,
    }


async def discover_managed_oss_schema(
    bff_client: Any,
    oss_path: str,
    file_format: str | None = None,
) -> dict[str, Any]:
    """Resolve schema from a DataWorks managed OSS datasource and exact external table."""
    try:
        location = parse_oss_path(oss_path)
    except ValueError:
        return _managed_failure({}, "", "invalid_location")

    normalized_format = infer_file_format(oss_path, file_format)
    if bff_client is None:
        return _managed_failure(location, normalized_format, "managed_channel_unavailable")

    try:
        sources = await bff_client.list_datasources()
    except Exception as exc:  # Cookie/BFF is an optional fallback boundary.
        logger.warning("Managed OSS datasource lookup failed: %s", type(exc).__name__)
        return _managed_failure(location, normalized_format, "managed_datasource_lookup_failed")

    bucket = str(location.get("bucket") or "")
    matches = [
        source
        for source in sources
        if isinstance(source, dict)
        and _datasource_type(source) == "oss"
        and _nested_exact_value(source, bucket)
    ]
    if not matches:
        return _managed_failure(location, normalized_format, "managed_datasource_not_found")

    source_name = _source_name(location)
    if not source_name:
        return _managed_failure(location, normalized_format, "registered_table_name_unavailable")

    try:
        tables = await bff_client.search_tables(source_name, page_size=50)
    except Exception as exc:
        logger.warning("Managed OSS table lookup failed: %s", type(exc).__name__)
        return _managed_failure(location, normalized_format, "registered_table_lookup_failed")

    exact_tables = [
        table
        for table in tables
        if isinstance(table, dict)
        and str(table.get("table_name") or "").strip().casefold() == source_name.casefold()
        and str(table.get("entity_guid") or "").strip()
    ]
    if not exact_tables:
        return _managed_failure(location, normalized_format, "registered_table_not_found")

    for table in exact_tables:
        try:
            ddl = await bff_client.get_creation_ddl(str(table["entity_guid"]))
        except Exception as exc:
            logger.warning("Managed OSS DDL lookup failed: %s", type(exc).__name__)
            continue
        if not ddl or not _ddl_location_matches(ddl, location):
            continue
        parsed = parse_ddl_structure(ddl)
        columns = [
            {
                "name": str(column.get("name") or "").strip(),
                "type": str(column.get("type") or "string").strip() or "string",
                "comment": str(column.get("comment") or "").strip(),
            }
            for column in parsed.get("columns") or []
            if str(column.get("name") or "").strip()
        ]
        if not columns:
            continue

        datasource_names = sorted(
            {name for source in matches if (name := _datasource_name(source))},
            key=str.casefold,
        )
        ingestion_mode = (
            "raw_json_text"
            if _raw_json_text_mode(ddl, columns, normalized_format)
            else "structured"
        )
        return {
            "success": True,
            "channel": "dataworks_managed_datasource",
            "source": "dataworks_managed_datasource",
            "location": location,
            "datasource_name": datasource_names[0] if datasource_names else "",
            "metadata_source": "registered_external_table",
            "file_format": normalized_format,
            "record_count": 0,
            "columns": columns,
            "ingestion_mode": ingestion_mode,
        }

    return _managed_failure(location, normalized_format, "registered_table_location_or_schema_mismatch")


async def discover_oss_schema_with_fallback(
    bff_client: Any,
    oss_path: str,
    file_format: str | None = None,
) -> dict[str, Any]:
    """Prefer managed metadata, then use bounded local OSS SDK sampling."""
    managed = await discover_managed_oss_schema(bff_client, oss_path, file_format)
    if managed.get("success"):
        return managed

    local = await asyncio.to_thread(discover_oss_schema, oss_path, file_format)
    if local.get("success"):
        result = dict(local)
        result["channel"] = "local_oss_sdk"
        result["source"] = "local_oss_sdk"
        result.setdefault("ingestion_mode", "structured")
        return result

    location = local.get("location") or managed.get("location") or {}
    normalized_format = str(local.get("file_format") or managed.get("file_format") or "")
    return {
        "success": False,
        "channel": "managed_then_local",
        "source": "managed_then_local",
        "location": location,
        "file_format": normalized_format,
        "error_code": "schema_discovery_unavailable",
        "error": "DataWorks 托管元数据与本地 OSS SDK 均未能完成字段探测",
        "next_action": "请检查托管数据源及同路径外部表配置，或直接提供字段定义。",
        "attempts": [
            {
                "channel": "dataworks_managed_datasource",
                "error_code": str(managed.get("error_code") or "managed_discovery_failed"),
            },
            {
                "channel": "local_oss_sdk",
                "error_code": str(local.get("error_code") or "local_discovery_failed"),
            },
        ],
        "attempted_endpoints": list(local.get("attempted_endpoints") or []),
        "detected_formats": list(local.get("detected_formats") or []),
    }

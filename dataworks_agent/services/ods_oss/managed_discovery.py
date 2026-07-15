"""Discover OSS schema through DataWorks managed metadata before local SDK access."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import PurePosixPath
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.governance.sql_lineage import parse_ddl_structure
from dataworks_agent.services.ods_oss.config import infer_file_format, parse_oss_path
from dataworks_agent.services.ods_oss.schema_discovery import (
    discover_oss_schema,
    infer_json_columns,
)

logger = logging.getLogger(__name__)

_LOCATION_RE = re.compile(r"\bLOCATION\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SAFE_SOURCE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RAW_JSON_COLUMN_NAMES = {
    "json",
    "json_data",
    "raw",
    "raw_data",
    "raw_json",
    "value",
    "content",
    "line",
}


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
    return str(actual.get("bucket") or "").casefold() == str(
        expected.get("bucket") or ""
    ).casefold() and str(actual.get("object_key") or "").strip("/") == str(
        expected.get("object_key") or ""
    ).strip("/")


def _raw_json_text_mode(ddl: str, columns: list[dict[str, Any]], file_format: str) -> bool:
    if file_format != "json" or len(columns) != 1 or "stored as textfile" not in ddl.lower():
        return False
    column = columns[0]
    name = str(column.get("name") or "").strip().lower()
    data_type = str(column.get("type") or "").strip().lower()
    return name in _RAW_JSON_COLUMN_NAMES and data_type in {"string", "varchar", "text"}


def _managed_failure(location: dict[str, Any], file_format: str, error_code: str) -> dict[str, Any]:
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
    *,
    include_registration: bool = False,
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
        partition_names = [
            str(partition.get("name") or "").strip()
            for partition in parsed.get("partitions") or []
            if str(partition.get("name") or "").strip()
        ]
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
        result = {
            "success": True,
            "channel": "dataworks_managed_datasource",
            "source": "dataworks_managed_datasource",
            "location": location,
            "datasource_name": datasource_names[0] if datasource_names else "",
            "metadata_source": "registered_external_table",
            "file_format": normalized_format,
            "record_count": 0,
            "columns": columns,
            "partition_columns": partition_names,
            "table_name": str(table.get("table_name") or source_name).strip(),
            "project": str(table.get("project") or "giikin_develop").strip(),
            "entity_guid": str(table.get("entity_guid") or "").strip(),
            "ingestion_mode": ingestion_mode,
        }
        if include_registration:
            result.update(
                {
                    "project": str(table.get("project") or "giikin_develop").strip(),
                    "table_name": str(table.get("table_name") or source_name).strip(),
                    "entity_guid": str(table.get("entity_guid") or "").strip(),
                    "source_table": (
                        f"{table.get('project')}.{table.get('table_name')}"
                        if table.get("project") and table.get("table_name")
                        else str(table.get("table_name") or source_name).strip()
                    ),
                }
            )
        return result

    return _managed_failure(
        location, normalized_format, "registered_table_location_or_schema_mismatch"
    )


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_IDENTIFIER.fullmatch(candidate) else ""


def _json_records_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, bytes):
        value = value.decode("utf-8-sig")
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line or line in {"[", "]"}:
                continue
            try:
                parsed_line = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed_line, dict):
                records.append(parsed_line)
        return records
    return _json_records_from_value(parsed)


def _row_value(row: Any, column_name: str, column_index: int = 0) -> Any:
    if isinstance(row, dict):
        if column_name in row:
            return row[column_name]
        lowered = column_name.casefold()
        for key, value in row.items():
            if str(key).casefold() == lowered:
                return value
        values = list(row.values())
        return values[column_index] if len(values) > column_index else None
    if isinstance(row, (list, tuple)):
        return row[column_index] if len(row) > column_index else None
    return row


async def _query_cookie_bff_rows(bff_client: Any, sql: str) -> tuple[list[str], list[Any]]:
    job_code = await asyncio.wait_for(
        bff_client.execute_sql(sql), timeout=settings.ask_data_timeout_seconds
    )
    if not job_code:
        raise RuntimeError(
            getattr(bff_client, "last_error", None) or "BFF did not return a query job"
        )
    completed = await asyncio.wait_for(
        bff_client.wait_job(job_code), timeout=settings.ask_data_timeout_seconds
    )
    if not completed:
        raise RuntimeError(getattr(bff_client, "last_error", None) or "BFF query did not complete")
    result = await asyncio.wait_for(
        bff_client.get_query_result(job_code), timeout=settings.ask_data_timeout_seconds
    )
    if not isinstance(result, dict):
        raise RuntimeError("BFF did not return a query result")
    headers = result.get("headerList") or []
    columns = [
        str(item.get("name", "")) if isinstance(item, dict) else str(item) for item in headers
    ]
    rows = list((result.get("bodyList") or [])[:100])
    return columns, rows


async def discover_managed_oss_sample(
    bff_client: Any,
    managed_result: dict[str, Any],
    *,
    max_records: int = 100,
) -> dict[str, Any]:
    """Infer raw JSON fields by querying the registered external table via Cookie/BFF."""
    if not managed_result.get("success"):
        return {
            **managed_result,
            "success": False,
            "error_code": "cookie_bff_sample_unavailable",
            "next_action": "Provide a real JSON sample or data_profile; direct OSS SDK access is not used here.",
        }
    if managed_result.get("ingestion_mode") != "raw_json_text":
        return managed_result
    if bff_client is None:
        return {
            **managed_result,
            "success": False,
            "error_code": "cookie_bff_sample_unavailable",
            "next_action": "Provide a real JSON sample or data_profile; Cookie/BFF is unavailable.",
        }

    project = _safe_identifier(managed_result.get("project"))
    table_name = _safe_identifier(managed_result.get("table_name"))
    raw_columns = managed_result.get("columns") or []
    raw_column = (
        _safe_identifier(raw_columns[0].get("name") if isinstance(raw_columns[0], dict) else "")
        if raw_columns
        else ""
    )
    if not project or not table_name or not raw_column:
        return {
            **managed_result,
            "success": False,
            "error_code": "cookie_bff_sample_unavailable",
            "next_action": "Provide a real JSON sample or data_profile because the registered table identifier is incomplete.",
        }

    sql = f"SELECT `{raw_column}` FROM `{project}`.`{table_name}` LIMIT {max(1, min(max_records, 100))}"
    try:
        headers, rows = await _query_cookie_bff_rows(bff_client, sql)
        column_index = next(
            (
                index
                for index, value in enumerate(headers)
                if value.casefold() == raw_column.casefold()
            ),
            0,
        )
        records: list[dict[str, Any]] = []
        for row in rows:
            records.extend(_json_records_from_value(_row_value(row, raw_column, column_index)))
            if len(records) >= max_records:
                break
        records = records[:max_records]
        if not records:
            raise ValueError("registered external table returned no JSON object sample")
        columns = infer_json_columns(records)
        return {
            **managed_result,
            "success": True,
            "columns": columns,
            "record_count": len(records),
            "sample_records": records,
            "sample_source": "cookie_bff_registered_external_table",
            "sample_query": sql,
            "raw_columns": raw_columns,
        }
    except Exception as exc:
        logger.warning("Cookie/BFF OSS sample query failed: %s", type(exc).__name__)
        return {
            **managed_result,
            "success": False,
            "error_code": "cookie_bff_sample_unavailable",
            "error": "Cookie/BFF could not return a JSON sample from the registered external table.",
            "next_action": "Provide a real JSON sample or data_profile; direct OSS SDK access is not used here.",
            "sample_query": sql,
        }


async def inspect_oss_directory_with_cookie(
    bff_client: Any,
    oss_path: str,
    file_format: str | None = None,
) -> dict[str, Any]:
    """Check an OSS prefix through the Cookie/BFF metadata channel only.

    The managed external-table lookup is the authoritative directory check for
    the modeling workflow.  Local OSS SDK sampling remains a separate, optional
    data-profiling fallback and must not be reported as a Cookie check.
    """
    result = await discover_managed_oss_schema(
        bff_client, oss_path, file_format, include_registration=True
    )
    location = result.get("location") or {}
    if not result.get("success"):
        result = dict(result)
        result["directory_check"] = {
            "success": False,
            "channel": "cookie_bff",
            "bucket": location.get("bucket"),
            "prefix": location.get("object_key") or "",
            "error_code": result.get("error_code"),
        }
        return result

    result = dict(result)
    result["directory_check"] = {
        "success": True,
        "channel": "cookie_bff",
        "bucket": location.get("bucket"),
        "prefix": location.get("object_key") or "",
        "is_prefix": bool(location.get("is_prefix")),
        "datasource_name": result.get("datasource_name"),
        "matched_external_table": result.get("table_name") or _source_name(location) or "",
        "entries": [result.get("sample_object")] if result.get("sample_object") else [],
    }
    return result


async def discover_oss_schema_with_fallback(
    bff_client: Any,
    oss_path: str,
    file_format: str | None = None,
    *,
    sample_managed_json: bool = False,
    managed_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer DataWorks managed metadata and optionally sample raw JSON through Cookie/BFF."""
    managed = managed_result or await discover_managed_oss_schema(
        bff_client,
        oss_path,
        file_format,
        include_registration=sample_managed_json,
    )
    if managed.get("success"):
        if sample_managed_json and managed.get("ingestion_mode") == "raw_json_text":
            return await discover_managed_oss_sample(bff_client, managed)
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

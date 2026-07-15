"""ODS OSS source and extraction SQL helpers."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

SUPPORTED_FILE_FORMATS = {"csv", "json", "parquet"}
OSS_NODE_PATH_PREFIX = "dataworks_agent/01_ODS"
OSS_DEFAULT_DEPENDENCIES = [{"type": "CrossCycleDependsOnSelf"}]
TOTAL_PHASES = 2
_SAFE_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_SAFE_ENDPOINT = re.compile(r"^oss-[a-z0-9-]+\.aliyuncs\.com$", re.IGNORECASE)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_oss_path(oss_path: str) -> dict[str, Any]:
    """Parse canonical and endpoint-style OSS paths."""
    raw = oss_path.strip()
    if not raw:
        raise ValueError("OSS 路径不能为空")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("OSS 路径不允许包含控制字符")
    if not raw.lower().startswith("oss://"):
        raw = f"oss://{raw}"
    parsed = urlsplit(raw)
    host = parsed.netloc.strip()
    if parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise ValueError("OSS 路径不允许包含查询参数、片段、用户信息或端口")
    if not host:
        raise ValueError("OSS 路径缺少 bucket")
    raw_path = parsed.path.lstrip("/")
    endpoint = ""
    if ".aliyuncs.com" in host.lower():
        if not _SAFE_ENDPOINT.fullmatch(host):
            raise ValueError("OSS endpoint 格式不合法")
        endpoint = host
        bucket, separator, object_key = raw_path.partition("/")
        if not bucket:
            raise ValueError("Endpoint 风格 OSS 路径缺少 bucket")
        if not separator:
            object_key = ""
    else:
        bucket = host
        object_key = raw_path
    if not _SAFE_BUCKET.fullmatch(bucket):
        raise ValueError(f"OSS bucket 名称不合法：{bucket}")
    if any(ord(char) < 32 or ord(char) == 127 for char in object_key):
        raise ValueError("OSS object key 不允许包含控制字符")
    is_prefix = parsed.path.endswith("/") and bool(object_key)
    object_key = object_key.rstrip("/")
    canonical_uri = f"oss://{bucket}"
    if object_key:
        canonical_uri += f"/{object_key}"
        if is_prefix:
            canonical_uri += "/"
    location_uri = f"oss://{endpoint}/{bucket}" if endpoint else f"oss://{bucket}"
    if object_key:
        location_uri += f"/{object_key}"
        if is_prefix:
            location_uri += "/"
    return {
        "endpoint": endpoint,
        "bucket": bucket,
        "object_key": object_key,
        "is_prefix": is_prefix,
        "canonical_uri": canonical_uri,
        "location_uri": location_uri,
    }


def normalize_file_format(file_format: str | None) -> str:
    normalized = (file_format or "").strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"jsonl", "ndjson", "json line", "json lines"}:
        return "json"
    return normalized


def infer_file_format(oss_path: str, file_format: str | None = None) -> str:
    explicit = normalize_file_format(file_format)
    if explicit:
        return explicit
    object_key = str(parse_oss_path(oss_path)["object_key"]).lower()
    if object_key.endswith((".json", ".jsonl", ".ndjson")):
        return "json"
    if object_key.endswith(".csv"):
        return "csv"
    if object_key.endswith(".parquet"):
        return "parquet"
    return ""


def validate_oss_config(oss_path: str, target_table: str, file_format: str) -> list[str]:
    errors: list[str] = []
    if not oss_path or not oss_path.strip():
        errors.append("OSS Bucket 路径不能为空")
    else:
        try:
            parse_oss_path(oss_path)
        except ValueError as exc:
            errors.append(str(exc))
    if not target_table or not target_table.strip():
        errors.append("目标 ODS 表名不能为空")
    elif not _SAFE_IDENTIFIER.fullmatch(target_table.strip().split(".")[-1]):
        errors.append("目标 ODS 表名不合法")
    normalized_format = normalize_file_format(file_format)
    if normalized_format not in SUPPORTED_FILE_FORMATS:
        errors.append(
            f"不支持的文件格式: {file_format}，支持的格式: {', '.join(sorted(SUPPORTED_FILE_FORMATS))}"
        )
    return errors


def ods_table_name(source_name: str, granularity: Literal["day", "hour"]) -> str:
    candidate = str(source_name or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"OSS source name is not a safe identifier: {source_name!r}")
    if granularity not in {"day", "hour"}:
        raise ValueError("granularity must be day or hour")
    return f"ods_mc_ads_data__{candidate}_{granularity}"


def build_ods_extract_sql(
    *,
    source_table: str,
    target_table: str,
    granularity: Literal["day", "hour"],
    source_partition_value: str | None,
    source_project: str = "giikin_develop",
    target_project: str = "giikin",
    source_partition: str = "pt",
) -> str:
    """Build ODS partition pre-creation and external-table extraction SQL."""
    for value, label in (
        (source_table, "source table"),
        (target_table, "target table"),
        (source_project, "source project"),
        (target_project, "target project"),
        (source_partition, "source partition"),
    ):
        if not _SAFE_IDENTIFIER.fullmatch(str(value or "")):
            raise ValueError(f"{label} is not a safe identifier")
    if granularity not in {"day", "hour"}:
        raise ValueError("granularity must be day or hour")
    if not source_partition_value:
        raise ValueError("source_partition_value is required for partitioned external tables")
    if any(ord(char) < 32 or ord(char) == 127 for char in source_partition_value):
        raise ValueError("source_partition_value contains control characters")
    partition = (
        "dt='${bizdate}'" if granularity == "day" else "dt='${gmtdate}', ht='${hour_last1h}'"
    )
    source_value = str(source_partition_value).replace("'", "''")
    return (
        f"ALTER TABLE {target_project}.{target_table}\n"
        f"ADD IF NOT EXISTS PARTITION ({partition});\n\n"
        f"INSERT OVERWRITE TABLE {target_project}.{target_table}\n"
        f"PARTITION ({partition})\n"
        f"SELECT json_data\nFROM {source_project}.{source_table}\n"
        f"WHERE {source_partition} = '{source_value}';"
    )

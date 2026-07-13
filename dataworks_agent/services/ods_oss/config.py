"""ODS OSS import — pure config/SQL helpers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

SUPPORTED_FILE_FORMATS = {"csv", "json", "parquet"}
OSS_NODE_PATH_PREFIX = "dataworks_agent/01_ODS"
OSS_DEFAULT_DEPENDENCIES = [{"type": "CrossCycleDependsOnSelf"}]
TOTAL_PHASES = 2
_SAFE_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_SAFE_ENDPOINT = re.compile(r"^oss-[a-z0-9-]+\.aliyuncs\.com$", re.IGNORECASE)


def parse_oss_path(oss_path: str) -> dict[str, Any]:
    """Parse canonical and endpoint-style OSS paths.

    Supported forms:
    - `oss://bucket/object-key`
    - `oss://oss-cn-region[-internal].aliyuncs.com/bucket/object-key`
    """
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
    return {
        "endpoint": endpoint,
        "bucket": bucket,
        "object_key": object_key,
        "is_prefix": is_prefix,
        "canonical_uri": canonical_uri,
    }


def normalize_file_format(file_format: str | None) -> str:
    """Normalize user-facing format aliases to pipeline formats."""
    normalized = (file_format or "").strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"jsonl", "ndjson", "json line", "json lines"}:
        return "json"
    return normalized


def infer_file_format(oss_path: str, file_format: str | None = None) -> str:
    """Infer a supported format from explicit input or object suffix."""
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
    """Validate OSS task configuration; empty list means valid."""
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
    normalized_format = normalize_file_format(file_format)
    if normalized_format not in SUPPORTED_FILE_FORMATS:
        errors.append(
            f"不支持的文件格式: {file_format}，"
            f"支持的格式: {', '.join(sorted(SUPPORTED_FILE_FORMATS))}"
        )
    return errors


def build_oss_import_sql(
    target_table: str,
    oss_path: str,
    file_format: str,
    wildcard: str = "",
    schedule_type: str = "day",
) -> str:
    """Generate LOAD OVERWRITE SQL for OSS → ODS import."""
    full_path = str(parse_oss_path(oss_path)["canonical_uri"]).rstrip("/")
    if wildcard:
        if any(ord(char) < 32 or ord(char) == 127 for char in wildcard):
            raise ValueError("OSS wildcard 不允许包含控制字符")
        full_path = f"{full_path}/{wildcard}"
    sql_path = full_path.replace("'", "''")

    if schedule_type in ("hour", "hourly"):
        partition_expr = "dt='${gmtdate}', ht='${hour_last1h}'"
    else:
        partition_expr = "dt='${bizdate}'"

    fmt = normalize_file_format(file_format)
    format_options = ""
    if fmt == "csv":
        format_options = (
            "    ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'\n"
            "    WITH SERDEPROPERTIES (\n"
            "        'separatorChar' = ',',\n"
            "        'quoteChar' = '\"'\n"
            "    )\n"
        )
    elif fmt == "json":
        format_options = "    ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe'\n"
    elif fmt == "parquet":
        format_options = "    STORED AS PARQUET\n"

    return (
        f"-- OSS 数据导入: {target_table}\n"
        f"-- 源路径: {sql_path}\n"
        f"-- 文件格式: {fmt}\n"
        f"LOAD OVERWRITE TABLE {target_table}\n"
        f"PARTITION ({partition_expr})\n"
        f"FROM LOCATION '{sql_path}'\n"
        f"{format_options}"
        f";"
    )

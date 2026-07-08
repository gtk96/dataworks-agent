"""ODS OSS import — pure config/SQL helpers."""

from __future__ import annotations

SUPPORTED_FILE_FORMATS = {"csv", "json", "parquet"}
OSS_NODE_PATH_PREFIX = "dataworks_agent/01_ODS"
OSS_DEFAULT_DEPENDENCIES = [{"type": "CrossCycleDependsOnSelf"}]
TOTAL_PHASES = 2


def parse_oss_path(oss_path: str) -> dict[str, str]:
    """Parse OSS path into bucket and object key."""
    path = oss_path.strip()
    if path.startswith("oss://"):
        path = path[len("oss://") :]
    parts = path.split("/", 1)
    bucket = parts[0]
    object_key = parts[1] if len(parts) > 1 else ""
    return {"bucket": bucket, "object_key": object_key.rstrip("/")}


def validate_oss_config(oss_path: str, target_table: str, file_format: str) -> list[str]:
    """Validate OSS task configuration; empty list means valid."""
    errors: list[str] = []
    if not oss_path or not oss_path.strip():
        errors.append("OSS Bucket 路径不能为空")
    if not target_table or not target_table.strip():
        errors.append("目标 ODS 表名不能为空")
    if file_format.lower() not in SUPPORTED_FILE_FORMATS:
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
    full_path = oss_path.rstrip("/")
    if wildcard:
        full_path = f"{full_path}/{wildcard}"

    if schedule_type in ("hour", "hourly"):
        partition_expr = "dt='${gmtdate}', ht='${hour_last1h}'"
    else:
        partition_expr = "dt='${bizdate}'"

    fmt = file_format.lower()
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
        f"-- 源路径: {full_path}\n"
        f"-- 文件格式: {fmt}\n"
        f"LOAD OVERWRITE TABLE {target_table}\n"
        f"PARTITION ({partition_expr})\n"
        f"FROM LOCATION '{full_path}'\n"
        f"{format_options}"
        f";"
    )

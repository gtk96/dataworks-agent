"""Table name generation and validation (from data-development-design table_name_service)."""

from __future__ import annotations

import re

MAX_TABLE_NAME_LENGTH = 128
TABLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

SOURCE_TYPE_PREFIXES = {
    "mysql": "ms",
    "oss": "oss",
    "hologres": "hl",
    "maxcompute": "mc",
    "odps": "mc",
    "elasticsearch": "es",
    "ftp": "ftp",
    "mongodb": "mg",
    "mongo": "mg",
    "polardb": "pl",
    "polar": "pl",
    "polar_db": "pl",
    "postgres": "pg",
    "postgresql": "pg",
    "oracle": "or",
    "sqlserver": "ss",
}


def source_type_prefix(source_type: str | None) -> str:
    """Return the ODS source-system prefix for a DataWorks datasource type."""
    normalized = (source_type or "mysql").strip().lower()
    return SOURCE_TYPE_PREFIXES.get(normalized, normalized or "ms")


def generate_ods_di_table_name(
    datasource_name: str,
    source_table_name: str,
    granularity: str,
    source_type: str | None = None,
) -> str:
    """Generate ODS DI table name: ods_{prefix}_{ds}__{table}_{granularity}."""
    prefix = source_type_prefix(source_type)
    return (
        f"ods_{prefix}_{datasource_name.lower()}__{source_table_name.lower()}_{granularity.lower()}"
    )


def generate_ods_realtime_table_name(
    database_schema: str,
    table_name: str,
    granularity: str,
) -> str:
    """Generate ODS realtime table name: ods_mc_{schema}__{table}_{granularity}."""
    return f"ods_mc_{database_schema.lower()}__{table_name.lower()}_{granularity.lower()}"


def generate_node_path(script_path_prefix: str, ods_table_name: str) -> str:
    """Generate DataWorks node path: {prefix}/{ods_table_name}."""
    return f"{script_path_prefix}/{ods_table_name}"


def validate_table_name(table_name: str) -> list[str]:
    """Validate a table name against MaxCompute naming rules."""
    errors: list[str] = []

    if not table_name:
        errors.append("表名不能为空")
        return errors

    if len(table_name) > MAX_TABLE_NAME_LENGTH:
        errors.append(
            f"表名长度超过 {MAX_TABLE_NAME_LENGTH} 字符限制（当前 {len(table_name)} 字符）"
        )

    if not TABLE_NAME_PATTERN.match(table_name):
        if table_name[0].isdigit():
            errors.append("表名不能以数字开头")
        if any(c.isupper() for c in table_name):
            errors.append("表名不能包含大写字母")
        if re.search(r"[^a-z0-9_]", table_name):
            errors.append("表名只能包含小写字母、数字和下划线")

    return errors


def is_valid_table_name(table_name: str) -> bool:
    """Return True if the table name passes all validation rules."""
    return len(validate_table_name(table_name)) == 0

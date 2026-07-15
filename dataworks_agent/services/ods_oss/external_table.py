"""External OSS table contracts and safe SQL generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dataworks_agent.schemas import assert_safe_table_name

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ExternalTableSpec:
    project: str
    table: str
    columns: tuple[tuple[str, str], ...]
    partition_columns: tuple[str, ...]
    file_format: str
    location: str


def _identifier(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} is not a safe identifier: {value!r}")
    assert_safe_table_name(value)
    return value


def _sql_literal(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("SQL literal contains control characters")
    return value.replace("'", "''")


def source_name_from_location(location: dict[str, Any]) -> str:
    key = str(location.get("object_key") or "").rstrip("/")
    name = key.rsplit("/", 1)[-1]
    if "." in name and not location.get("is_prefix"):
        name = name.rsplit(".", 1)[0]
    return _identifier(name, "external table name")


def build_external_table_ddl(spec: ExternalTableSpec) -> str:
    project = _identifier(spec.project, "external project")
    table = _identifier(spec.table, "external table")
    if not spec.columns:
        raise ValueError("external table requires at least one column")
    columns = ",\n".join(
        f"    `{_identifier(name, 'column')}` {str(data_type).strip().upper()}"
        for name, data_type in spec.columns
    )
    partitions = ""
    if spec.partition_columns:
        partitions = "\nPARTITIONED BY (" + ", ".join(
            f"`{_identifier(name, 'partition column')}` STRING"
            for name in spec.partition_columns
        ) + ")"
    fmt = str(spec.file_format or "json").strip().lower()
    storage = "TEXTFILE" if fmt == "json" else fmt.upper()
    location = _sql_literal(str(spec.location).strip().rstrip("/"))
    return (
        f"CREATE EXTERNAL TABLE IF NOT EXISTS {project}.{table} (\n{columns}\n)"
        f"{partitions}\nSTORED AS {storage}\nLOCATION '{location}';"
    )


def validate_external_table_compatibility(
    spec: ExternalTableSpec, observed: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if str(observed.get("project") or spec.project).casefold() != spec.project.casefold():
        errors.append("external table project mismatch")
    if str(observed.get("table_name") or observed.get("table") or "").casefold() != spec.table.casefold():
        errors.append("external table name mismatch")
    expected_location = str(spec.location).rstrip("/").casefold()
    actual_location = str(observed.get("location") or "").rstrip("/").casefold()
    if actual_location and actual_location != expected_location:
        errors.append("external table LOCATION mismatch")
    actual_columns = {
        str(item.get("name") or "").casefold(): str(item.get("type") or "").upper()
        for item in observed.get("columns") or []
        if isinstance(item, dict)
    }
    for name, data_type in spec.columns:
        if actual_columns and actual_columns.get(name.casefold()) != data_type.upper():
            errors.append(f"external column mismatch: {name}")
    actual_partitions = [str(value).casefold() for value in observed.get("partition_columns") or []]
    if actual_partitions and actual_partitions != [value.casefold() for value in spec.partition_columns]:
        errors.append("external table partition mismatch")
    return errors

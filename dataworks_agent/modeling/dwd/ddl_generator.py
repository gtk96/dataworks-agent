"""DWD DDL generator — MaxCompute CREATE TABLE from structured metadata."""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

_SIMPLE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_QUALIFIED_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
_VALID_TYPES = {
    "STRING",
    "BIGINT",
    "INT",
    "SMALLINT",
    "TINYINT",
    "DOUBLE",
    "FLOAT",
    "BOOLEAN",
    "DATETIME",
    "TIMESTAMP",
    "DATE",
    "BINARY",
    "ARRAY",
    "MAP",
    "STRUCT",
}
_LIFECYCLE_MAP: dict[str, int] = {
    "daily": 7,
    "hourly": 7,
    "monthly": 30,
    "full": -1,
    "zipper": -1,
}


def _validate_simple_identifier(value: str, field_name: str) -> str:
    value = value.strip()
    if not _SIMPLE_IDENTIFIER.match(value):
        raise ValueError(f"{field_name} is not a valid SQL identifier: {value!r}")
    return value


def _validate_qualified_identifier(value: str, field_name: str) -> str:
    value = value.strip()
    if not _QUALIFIED_IDENTIFIER.match(value):
        raise ValueError(f"{field_name} is not a valid SQL identifier: {value!r}")
    return value


def _is_valid_type(type_str: str) -> bool:
    base = type_str.split("(")[0].strip().upper()
    return base in _VALID_TYPES or base == "DECIMAL"


class ColumnDef(BaseModel):
    name: str
    type: str = "STRING"
    comment: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_simple_identifier(v, "column name")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if not _is_valid_type(v):
            raise ValueError(f"Unsupported column type: {v!r}")
        if "(" not in v:
            return v.upper()
        return v.split("(")[0].upper() + "(" + v.split("(", 1)[1]


class DDLMetadata(BaseModel):
    target_table_name: str
    table_comment: str | None = None
    columns: list[ColumnDef]
    partition_fields: list[ColumnDef] | None = None
    update_mode: str = "daily"
    lifecycle: int | None = None

    @field_validator("target_table_name")
    @classmethod
    def validate_table_name(cls, v: str) -> str:
        return _validate_qualified_identifier(v, "target_table_name")

    @field_validator("update_mode")
    @classmethod
    def validate_update_mode(cls, v: str) -> str:
        allowed = {"daily", "hourly", "monthly", "zipper", "full"}
        if v not in allowed:
            raise ValueError(f"update_mode must be one of {allowed}, got {v!r}")
        return v


class DwdDDLGenerator:
    """Generate MaxCompute CREATE TABLE DDL from structured metadata."""

    def generate(self, metadata: DDLMetadata) -> str:
        parts: list[str] = []
        parts.append(f"drop table if exists {metadata.target_table_name};")
        parts.append(f"create table {metadata.target_table_name} (")

        col_lines: list[str] = []
        for col in metadata.columns:
            line = f"    {col.name} {col.type}"
            if col.comment:
                escaped = col.comment.replace("'", "\\'")
                line += f" COMMENT '{escaped}'"
            col_lines.append(line)
        parts.append(",\n".join(col_lines))
        parts.append(")")

        if metadata.table_comment:
            escaped = metadata.table_comment.replace("'", "\\'")
            parts.append(f"COMMENT '{escaped}'")

        if metadata.partition_fields:
            pf_parts: list[str] = []
            for pf in metadata.partition_fields:
                pf_str = f"{pf.name} {pf.type}"
                if pf.comment:
                    escaped = pf.comment.replace("'", "\\'")
                    pf_str += f" COMMENT '{escaped}'"
                pf_parts.append(pf_str)
            parts.append(f"PARTITIONED BY ({', '.join(pf_parts)})")

        return "\n".join(parts) + "\n;"

    def from_structured_metadata(self, structured_metadata: dict) -> DDLMetadata:
        targets = structured_metadata.get("targets", [])
        if not targets:
            raise ValueError("structured_metadata must contain at least one target")

        target = targets[0]
        table_name = target.get("table_name", "")
        if not table_name:
            raise ValueError("target.table_name is required")

        columns: list[ColumnDef] = []
        raw_fields = target.get("fields", [])
        partition_field_names = set(target.get("partition_fields") or [])

        for field in raw_fields:
            name = field.get("name", "")
            if not name or name in partition_field_names:
                continue
            columns.append(
                ColumnDef(
                    name=name,
                    type=field.get("type", "STRING"),
                    comment=field.get("comment") or field.get("description"),
                )
            )

        if not columns:
            raise ValueError("No columns found in target fields")

        partition_defs: list[ColumnDef] | None = None
        raw_partition = target.get("partition_fields") or []
        if raw_partition:
            partition_defs = []
            for pf_name in raw_partition:
                pf_info = next((f for f in raw_fields if f.get("name") == pf_name), None)
                partition_defs.append(
                    ColumnDef(
                        name=pf_name,
                        type=pf_info.get("type", "STRING") if pf_info else "STRING",
                        comment=(
                            pf_info.get("comment")
                            or pf_info.get("description")
                            or self._default_partition_comment(pf_name)
                        )
                        if pf_info
                        else self._default_partition_comment(pf_name),
                    )
                )

        return DDLMetadata(
            target_table_name=table_name,
            table_comment=target.get("table_comment") or target.get("table_description"),
            columns=columns,
            partition_fields=partition_defs,
            update_mode=target.get("update_mode", "daily"),
        )

    @staticmethod
    def _default_partition_comment(partition_name: str) -> str:
        if partition_name == "dt":
            return "业务日期分区，格式 yyyy-MM-dd"
        if partition_name == "ht":
            return "小时分区 00~23"
        return f"{partition_name} partition"

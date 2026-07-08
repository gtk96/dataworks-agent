"""Pydantic schemas for DWD SQL/DDL generation (from data-development-design)."""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

_DANGEROUS_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)
_DANGEROUS_CHARS = re.compile(r"(--|;|/\*|\*/)")
_SIMPLE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_QUALIFIED_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
_ON_VALUE = r"""(?:[a-zA-Z_][a-zA-Z0-9_.]*|'[^']*'|"[^"]*"|\$\{[^}]+\}|\d+)"""
_ON_SINGLE = rf"[a-zA-Z_][a-zA-Z0-9_.]*\s*=\s*{_ON_VALUE}"
_SAFE_ON_CONDITION = re.compile(rf"^\s*{_ON_SINGLE}(\s+[Aa][Nn][Dd]\s+{_ON_SINGLE})*\s*$")


def _check_dangerous_sql(value: str, field_name: str) -> None:
    if _DANGEROUS_KEYWORDS.search(value):
        raise ValueError(f"{field_name} contains forbidden SQL keyword: {value!r}")
    if _DANGEROUS_CHARS.search(value):
        raise ValueError(f"{field_name} contains forbidden characters (;, --, /*): {value!r}")


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


class SourceInfo(BaseModel):
    table_name: str
    alias: str

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, v: str) -> str:
        return _validate_qualified_identifier(v, "table_name")

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, v: str) -> str:
        return _validate_simple_identifier(v, "alias")


class FieldMappingInfo(BaseModel):
    source_alias: str
    source_field_name: str
    target_field_name: str
    transform_sql: str | None = None
    field_category: str = "normal"
    apply_coalesce: bool = True

    @field_validator("source_alias", "source_field_name", "target_field_name")
    @classmethod
    def validate_identifiers(cls, v: str, info) -> str:
        return _validate_simple_identifier(v, info.field_name)

    @field_validator("transform_sql")
    @classmethod
    def validate_transform_sql(cls, v: str | None) -> str | None:
        if v is not None:
            _check_dangerous_sql(v, "transform_sql")
        return v


class JoinInfo(BaseModel):
    join_type: str
    right_table_name: str
    right_alias: str
    on_condition: str

    @field_validator("join_type")
    @classmethod
    def validate_join_type(cls, v: str) -> str:
        allowed = {"INNER", "LEFT", "RIGHT", "FULL"}
        if v.upper() not in allowed:
            raise ValueError(f"join_type must be one of {allowed}, got {v!r}")
        return v.upper()

    @field_validator("right_table_name")
    @classmethod
    def validate_right_table_name(cls, v: str) -> str:
        return _validate_qualified_identifier(v, "right_table_name")

    @field_validator("right_alias")
    @classmethod
    def validate_right_alias(cls, v: str) -> str:
        return _validate_simple_identifier(v, "right_alias")

    @field_validator("on_condition")
    @classmethod
    def validate_on_condition(cls, v: str) -> str:
        _check_dangerous_sql(v, "on_condition")
        if not _SAFE_ON_CONDITION.match(v.strip()):
            raise ValueError(
                f"on_condition must be in format 'alias.field = alias.field [AND ...]', got: {v!r}"
            )
        return v


class StructuredMetadata(BaseModel):
    target_table_name: str
    update_mode: str
    partition_fields: list[str]
    logical_primary_keys: list[str]
    master_table: SourceInfo
    sources: list[SourceInfo]
    field_mappings: list[FieldMappingInfo]
    joins: list[JoinInfo]

    @field_validator("target_table_name")
    @classmethod
    def validate_target_table(cls, v: str) -> str:
        return _validate_qualified_identifier(v, "target_table_name")

    @field_validator("update_mode")
    @classmethod
    def validate_update_mode(cls, v: str) -> str:
        allowed = {"daily", "hourly", "monthly", "zipper", "full"}
        if v not in allowed:
            raise ValueError(f"update_mode must be one of {allowed}, got {v!r}")
        return v

    @field_validator("partition_fields", "logical_primary_keys")
    @classmethod
    def validate_field_lists(cls, v: list[str], info) -> list[str]:
        stripped = [item.strip() for item in v]
        for item in stripped:
            _validate_simple_identifier(item, info.field_name)
        return stripped

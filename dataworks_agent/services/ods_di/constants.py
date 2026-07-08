"""ODS DI pipeline constants."""

from __future__ import annotations

from typing import Any

WHERE_FIELD_CANDIDATES: list[str] = [
    "update_time",
    "updated_at",
    "gmt_modified",
    "modify_time",
    "updated_time",
    "last_update_time",
    "last_modified",
    "gmt_update",
    "update_at",
    "modified_at",
    "modified_time",
    "up_time",
    "upd_time",
    "upt_time",
    "gmt_modify",
    "create_time",
    "created_at",
    "gmt_create",
    "created_time",
    "create_at",
    "creation_time",
]

DI_DEFAULT_DEPENDENCIES: list[dict[str, Any]] = [
    {"type": "CrossCycleDependsOnSelf"},
]

DATETIME_TYPES = {"datetime", "timestamp", "varchar", "char", "text", "date", "string"}
UNIX_INT_TYPES = {"int", "bigint", "tinyint", "smallint", "mediumint", "integer"}
INIT_PARTITION_DATE = "20170101"
INIT_PARTITION_HOUR = "00"

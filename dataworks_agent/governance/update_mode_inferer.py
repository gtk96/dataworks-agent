"""Infer DWD update mode from source table suffixes."""

from __future__ import annotations

from dataclasses import dataclass

SUFFIX_TO_DWD_UPDATE_MODE = {
    "hour": "hourly",
    "hourly": "hourly",
    "day": "all",
    "all": "all",
}
UNSUPPORTED_SUFFIXES = {"min", "week", "mon", "qtr", "year", "his", "static"}
DWD_MODE_TO_SQL_MODE = {
    "hourly": "hourly",
    "all": "full",
}
DWD_MODE_TO_PARTITIONS = {
    "hourly": ["dt", "ht"],
    "all": ["dt"],
}


@dataclass(frozen=True)
class UpdateModeResolution:
    dwd_update_mode: str
    sql_update_mode: str
    partition_fields: list[str]


def infer_update_mode(table_name: str) -> UpdateModeResolution:
    """Infer update mode from the last underscore-delimited table suffix."""
    suffix = table_name.strip().lower().rsplit("_", 1)[-1]
    if suffix in UNSUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported update mode suffix: {suffix}")
    dwd_update_mode = SUFFIX_TO_DWD_UPDATE_MODE.get(suffix)
    if dwd_update_mode is None:
        raise ValueError(f"cannot infer update mode from table name: {table_name!r}")
    return UpdateModeResolution(
        dwd_update_mode=dwd_update_mode,
        sql_update_mode=DWD_MODE_TO_SQL_MODE[dwd_update_mode],
        partition_fields=list(DWD_MODE_TO_PARTITIONS[dwd_update_mode]),
    )

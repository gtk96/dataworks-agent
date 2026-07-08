"""Schedule configuration helpers (from data-development-design schedule_service)."""

from __future__ import annotations

from typing import Any, Literal

DAILY_SQL_PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "bizdate",
        "type": "System",
        "value": "${workspace.bizdate}",
        "scope": "NodeParameter",
    },
]

HOURLY_SQL_PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "bizdate",
        "type": "System",
        "value": "${workspace.bizdate}",
        "scope": "NodeParameter",
    },
    {
        "name": "gmtdate",
        "type": "System",
        "value": "${workspace.gmtdate}",
        "scope": "NodeParameter",
    },
    {
        "name": "gmtdate_last1h",
        "type": "System",
        "value": "${workspace.gmtdate_last1h}",
        "scope": "NodeParameter",
    },
    {
        "name": "hour_last1h",
        "type": "System",
        "value": "${workspace.hour_last1h}",
        "scope": "NodeParameter",
    },
    {
        "name": "hour_last2h",
        "type": "System",
        "value": "${workspace.hour_last2h}",
        "scope": "NodeParameter",
    },
]
# DWD 专用参数源在 scripts/push_dwd_params.py:DWD_SQL_PARAMETERS(包含 gmtdate_next1d)。
# DWD 表 DML 用 ${gmtdate_next1d} 预创建下小时分区,必须用 DWD_SQL_PARAMETERS,不能用上面这套。
DWD_SQL_PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "bizdate",
        "type": "System",
        "value": "${workspace.bizdate}",
        "scope": "NodeParameter",
    },
    {
        "name": "gmtdate",
        "type": "System",
        "value": "${workspace.gmtdate}",
        "scope": "NodeParameter",
    },
    {
        "name": "gmtdate_last1h",
        "type": "System",
        "value": "${workspace.gmtdate_last1h}",
        "scope": "NodeParameter",
    },
    {
        "name": "gmtdate_next1d",
        "type": "System",
        "value": "$[yyyymmdd+1]",
        "scope": "NodeParameter",
    },
    {
        "name": "hour_last1h",
        "type": "System",
        "value": "${workspace.hour_last1h}",
        "scope": "NodeParameter",
    },
    {
        "name": "hour_last2h",
        "type": "System",
        "value": "${workspace.hour_last2h}",
        "scope": "NodeParameter",
    },
]

HOURLY_SUFFIXES = {"hour", "hourly"}
_DAY_WINDOW_TOTAL_MINUTES = 419

Granularity = Literal["day", "hour", "all", "hourly"]


def get_cycle_type(granularity: Granularity) -> str:
    """Map granularity to DataWorks cycle type (Daily / NotDaily)."""
    if granularity in ("hour", "hourly"):
        return "NotDaily"
    if granularity in ("day", "all"):
        return "Daily"
    raise ValueError(
        f"Invalid granularity: {granularity!r}. Must be one of: day, hour, all, hourly"
    )


def generate_cron(granularity: Granularity, hour: int = 0, minute: int = 0) -> str:
    """Generate a DataWorks 6-field Cron expression."""
    if not (0 <= minute <= 59):
        raise ValueError(f"Minute must be 0-59, got {minute}")
    if not (0 <= hour <= 23):
        raise ValueError(f"Hour must be 0-23, got {hour}")

    if granularity in ("hour", "hourly"):
        return f"00 {minute:02d} 00-23/1 * * ?"
    if granularity in ("day", "all"):
        return f"00 {minute:02d} {hour:02d} * * ?"
    raise ValueError(
        f"Invalid granularity: {granularity!r}. Must be one of: day, hour, all, hourly"
    )


def auto_distribute(
    task_index: int,
    total_tasks: int,
    granularity: Granularity,
) -> dict[str, int]:
    """Compute evenly distributed schedule time for a task in a batch."""
    if total_tasks < 1:
        raise ValueError(f"total_tasks must be ≥ 1, got {total_tasks}")
    if not (0 <= task_index < total_tasks):
        raise ValueError(f"task_index must be in [0, {total_tasks}), got {task_index}")

    if granularity in ("hour", "hourly"):
        minute = int(task_index * 60 / total_tasks) % 60
        return {"hour": 0, "minute": minute}

    if granularity in ("day", "all"):
        offset = int(task_index * _DAY_WINDOW_TOTAL_MINUTES / total_tasks)
        hour = offset // 60
        minute = offset % 60 + 1
        return {"hour": hour, "minute": minute}

    raise ValueError(
        f"Invalid granularity: {granularity!r}. Must be one of: day, hour, all, hourly"
    )


def infer_schedule_type(target_table_name: str) -> str:
    """Infer Daily / NotDaily from target table name suffix."""
    suffix = target_table_name.rsplit("_", 1)[-1].lower() if "_" in target_table_name else ""
    return "NotDaily" if suffix in HOURLY_SUFFIXES else "Daily"


def get_schedule_config(granularity: Granularity) -> dict[str, Any]:
    """Return cycle_type, default cron, and SQL parameters for a granularity."""
    cycle_type = get_cycle_type(granularity)
    if cycle_type == "NotDaily":
        return {
            "cycle_type": "NotDaily",
            "cron": "00 30 00-23/1 * * ?",
            "parameters": HOURLY_SQL_PARAMETERS,
        }
    return {
        "cycle_type": "Daily",
        "cron": "00 00 06 * * ?",
        "parameters": DAILY_SQL_PARAMETERS,
    }


def granularity_from_update_method(update_method: str) -> Granularity:
    """Map dataworks UpdateMethod value to schedule granularity."""
    mapping: dict[str, Granularity] = {
        "day": "day",
        "hour": "hour",
        "hourly": "hourly",
        "all": "all",
    }
    if update_method not in mapping:
        raise ValueError(f"Unsupported update_method for schedule: {update_method!r}")
    return mapping[update_method]

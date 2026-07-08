"""ODS Realtime sync — pure helper functions."""

from __future__ import annotations

import re
from typing import Any

from dataworks_agent.naming import generate_node_path, generate_ods_realtime_table_name
from dataworks_agent.naming.schedule import generate_cron

REALTIME_NODE_PATH_PREFIX = "dataworks_agent/01_ODS"
REALTIME_CYCLE_TYPE = "NotDaily"
REALTIME_DEFAULT_DEPENDENCIES = [{"type": "CrossCycleDependsOnSelf"}]
TOTAL_PHASES = 2


def extract_fields_from_select_dml(select_dml: str | None) -> list[str]:
    """Extract field names between SELECT and FROM, stripping trailing dt/ht."""
    if not select_dml:
        return []

    pattern = r"SELECT\s+(.*?)\s+FROM"
    match = re.search(pattern, select_dml, re.IGNORECASE | re.DOTALL)
    if not match:
        return []

    fields_section = match.group(1).strip()
    fields: list[str] = []
    current = ""
    depth = 0
    for ch in fields_section:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            field = current.strip()
            if field:
                fields.append(field)
            current = ""
        else:
            current += ch
    if current.strip():
        fields.append(current.strip())

    filtered: list[str] = []
    skip_tail = True
    for i in range(len(fields) - 1, -1, -1):
        field_name = re.split(r"\s+", fields[i].strip().lower())[0].strip("`\"'")
        if skip_tail and field_name in ("dt", "ht"):
            continue
        skip_tail = False
        filtered.insert(0, fields[i])
    return filtered


def match_delta_table(
    database_schema: str,
    table_name: str,
    sync_rows: list[dict[str, Any]],
) -> str | None:
    """Match delta table from sync job cache rows."""
    expected = f"{database_schema}__{table_name}"
    for row in sync_rows:
        dst = row.get("dst_table") or ""
        candidate = dst[: -len("_delta")] if dst.endswith("_delta") else dst
        if candidate == expected:
            return dst
    return None


def build_realtime_node_path(
    ods_table_name: str,
    node_path_prefix: str = REALTIME_NODE_PATH_PREFIX,
) -> str:
    return generate_node_path(node_path_prefix, ods_table_name)


def generate_insert_sql(
    ods_table_name: str,
    delta_table_name: str,
    fields: list[str],
    project_space: str,
    source_project: str | None = None,
) -> str:
    """Generate INSERT OVERWRITE SQL for realtime ODS sync."""
    if not fields:
        return ""
    from_project = source_project or project_space
    columns_str = ",\n  ".join(fields)
    return (
        f"insert overwrite table {project_space}.{ods_table_name} "
        f"partition (dt='${{gmtdate}}', ht='${{hour_last1h}}')\n"
        f"SELECT\n"
        f"  {columns_str}\n"
        f"from {from_project}.{delta_table_name}\n"
        f"where dw_update_time >= '${{gmtdate_last2h}} ${{hour_last2h}}:00:00';"
    )


def preprocess_realtime_task(
    *,
    database_schema: str,
    table_name: str,
    sync_rows: list[dict[str, Any]],
    granularity: str = "hour",
    node_path_prefix: str = REALTIME_NODE_PATH_PREFIX,
    schedule_minute: int = 0,
) -> dict[str, Any]:
    """Phase 1: match delta table and derive ODS node metadata."""
    delta_table = match_delta_table(database_schema, table_name, sync_rows)
    if not delta_table:
        return {
            "success": False,
            "error": f"未匹配 delta 表: {database_schema}__{table_name}",
        }

    ods_table_name = generate_ods_realtime_table_name(database_schema, table_name, granularity)
    node_path = build_realtime_node_path(ods_table_name, node_path_prefix)
    cron_expr = generate_cron("hour", minute=schedule_minute)

    return {
        "success": True,
        "delta_table": delta_table,
        "ods_table_name": ods_table_name,
        "node_path": node_path,
        "cron_expr": cron_expr,
        "cycle_type": REALTIME_CYCLE_TYPE,
    }

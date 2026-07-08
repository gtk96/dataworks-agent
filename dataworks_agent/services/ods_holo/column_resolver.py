"""Resolve Holo ODS source/target column metadata (shared by preview API and DML generator)."""

from __future__ import annotations

from typing import Any, Literal

from dataworks_agent.config import settings
from dataworks_agent.services.ods_di.di_config import infer_split_pk
from dataworks_agent.services.ods_di.field_infer import (
    infer_fields,
    query_columns,
    query_columns_from_ddl_registry,
)
from dataworks_agent.services.ods_di.where_infer import (
    default_where_mode,
    infer_incremental_where,
    list_where_options,
)
from dataworks_agent.services.ods_holo.local_ddl_registry import (
    query_columns_from_local_template,
    query_columns_from_mc_ods_ddl,
)

MetadataSource = Literal[
    "snapshot", "ddl_registry", "local_template", "mc_ods_ddl", "inferred", "failed"
]


def _append_ods_partition_columns(target_names: list[str], granularity: str) -> list[str]:
    gran = granularity.lower()
    names = list(target_names)
    if gran in {"hour", "hourly", "min"}:
        if not any(n.lower() == "update_ht" for n in names):
            names.append("update_ht")
        for part in ("dt", "ht"):
            if not any(n.lower() == part for n in names):
                names.append(part)
    elif not any(n.lower() == "dt" for n in names):
        names.append("dt")
    return names


async def load_holo_ods_columns(
    bff: Any,
    mcp: Any,
    holo_schema: str,
    source_table: str,
    granularity: str,
    where_mode: str = "auto",
) -> dict[str, Any]:
    """Resolve source column metadata and ODS target column order."""
    metadata_source: MetadataSource = "failed"
    source_rows: list[dict[str, Any]] = []

    snapshot_rows = await query_columns(bff, mcp, holo_schema, source_table)
    if snapshot_rows:
        source_rows = snapshot_rows
        metadata_source = "snapshot"

    registry_rows = await query_columns_from_ddl_registry(
        bff, mcp, holo_schema, source_table, granularity
    )

    target_columns: list[str] = []
    if registry_rows:
        metadata_source = metadata_source if metadata_source != "failed" else "ddl_registry"
        target_columns = _append_ods_partition_columns(
            [c["column_name"] for c in registry_rows],
            granularity,
        )
        if not source_rows:
            source_rows = registry_rows
    elif source_rows:
        target_columns = _append_ods_partition_columns(
            [c["column_name"] for c in source_rows],
            granularity,
        )

    if not source_rows:
        local_rows = query_columns_from_local_template(holo_schema, source_table, granularity)
        if local_rows:
            metadata_source = "local_template"
            source_rows = local_rows
            if not target_columns:
                target_columns = _append_ods_partition_columns(
                    [c["column_name"] for c in local_rows],
                    granularity,
                )

    if not source_rows:
        mc_rows = await query_columns_from_mc_ods_ddl(
            bff, mcp, holo_schema, source_table, granularity
        )
        if mc_rows:
            metadata_source = "mc_ods_ddl"
            source_rows = mc_rows
            if not target_columns:
                target_columns = _append_ods_partition_columns(
                    [c["column_name"] for c in mc_rows],
                    granularity,
                )

    if not source_rows:
        field_step = await infer_fields(bff, mcp, holo_schema, source_table, granularity)
        if field_step.get("status") == "ok":
            metadata_source = "inferred"
            source_rows = [
                {"column_name": name, "data_type": "string", "column_key": ""}
                for name in field_step.get("columns") or []
            ]
            target_columns = _append_ods_partition_columns(
                [c["column_name"] for c in source_rows],
                granularity,
            )

    infer_base = snapshot_rows or registry_rows or source_rows
    split_pk = infer_split_pk(infer_base, source_table) if infer_base else ""
    where_options = list_where_options(infer_base) if infer_base else []
    resolved_mode = (
        where_mode
        if where_mode and where_mode != "auto"
        else (default_where_mode(infer_base) if infer_base else "none")
    )
    where_meta = (
        infer_incremental_where(infer_base, granularity, resolved_mode)
        if infer_base
        else {
            "where_clause": "",
            "where_label": "",
            "where_field": "",
            "where_type": "none",
            "where_mode": "none",
        }
    )

    return {
        "status": "ok" if source_rows else "failed",
        "metadata_source": metadata_source,
        "holo_read_ref": f"{holo_schema}.{source_table}",
        "source_columns": source_rows,
        "target_columns": target_columns,
        "column_count": len(source_rows),
        "split_pk": split_pk,
        "where_field": where_meta.get("where_label") or where_meta.get("where_field", ""),
        "where_type": where_meta.get("where_type", "none"),
        "where_clause": where_meta.get("where_clause", ""),
        "where_mode": where_meta.get("where_mode", resolved_mode),
        "default_where_mode": default_where_mode(infer_base) if infer_base else "none",
        "where_options": where_options,
        "error": ""
        if source_rows
        else (
            f"无法解析 {holo_schema}.{source_table} 字段；"
            "请确认 schema 快照、dwd_pub_ods_ddl_all、"
            f"本地模板 {settings.sql_template_root} 或 dataworks ODS 表"
        ),
    }

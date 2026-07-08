"""Build StructuredMetadata / DDL inputs from API payloads."""

from __future__ import annotations

from dataworks_agent.modeling.dwd.schemas import (
    FieldMappingInfo,
    JoinInfo,
    SourceInfo,
    StructuredMetadata,
)


def build_structured_metadata(payload: dict) -> StructuredMetadata:
    """Convert visual-modeler JSON payload to StructuredMetadata."""
    targets = payload.get("targets") or []
    sources = payload.get("sources") or []
    if not targets:
        raise ValueError("targets must not be empty")
    if not sources:
        raise ValueError("sources must not be empty")

    target = targets[0]
    master = next((s for s in sources if s.get("is_master")), sources[0])
    master_alias = master.get("alias") or "T1"
    master_table = master.get("table_name") or ""
    if not master_table:
        raise ValueError("master source table_name is required")

    source_infos = [
        SourceInfo(
            table_name=s["table_name"],
            alias=s.get("alias") or f"T{idx + 1}",
        )
        for idx, s in enumerate(sources)
        if s.get("table_name")
    ]

    field_mappings: list[FieldMappingInfo] = []
    for fm in payload.get("field_mappings") or []:
        alias = fm.get("source_alias") or master_alias
        field_mappings.append(
            FieldMappingInfo(
                source_alias=alias,
                source_field_name=fm["source_field_name"],
                target_field_name=fm["target_field_name"],
                transform_sql=fm.get("transform_sql"),
                field_category=fm.get("field_category") or "normal",
                apply_coalesce=fm.get("apply_coalesce", True),
            )
        )

    joins: list[JoinInfo] = []
    for join in payload.get("joins") or []:
        joins.append(
            JoinInfo(
                join_type=join.get("join_type") or "LEFT",
                right_table_name=join["right_table_name"],
                right_alias=join["right_alias"],
                on_condition=join["on_condition"],
            )
        )

    partition_fields = target.get("partition_fields") or ["dt"]
    logical_primary_keys = target.get("logical_primary_keys") or []
    update_mode = target.get("update_mode") or "daily"

    return StructuredMetadata(
        target_table_name=target["table_name"],
        update_mode=update_mode,
        partition_fields=partition_fields,
        logical_primary_keys=logical_primary_keys,
        master_table=SourceInfo(table_name=master_table, alias=master_alias),
        sources=source_infos,
        field_mappings=field_mappings,
        joins=joins,
    )

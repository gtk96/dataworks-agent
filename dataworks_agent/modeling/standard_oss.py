"""Standard OSS JSON-to-DWD artifacts for the TikTok material report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataworks_agent.governance.ddl_checker import check_ddl
from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
from dataworks_agent.modeling.root_checker import RootChecker
from dataworks_agent.schemas import assert_safe_table_name

MATERIAL_REPORT_ODS_TABLE = "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
MATERIAL_REPORT_DWD_TABLE = "dwd_mkt_tiktok_smart_plus_material_report_hour"
MATERIAL_REPORT_TEMPLATE_TASK_ID = "10002152501"
MATERIAL_REPORT_TEMPLATE_NODE = "dwd_mkt_ad_country_insights_tiktok_hour"
MATERIAL_REPORT_TEMPLATE_CRON = "00 03 00-23/1 * * ?"
MATERIAL_REPORT_SCHEDULE_PARAMETERS = ("gmtdate", "hour_last1h")
MATERIAL_REPORT_TEMPLATE_PARENT_REFERENCES = (
    "ods_mc_ads_data__tiktok_ad_country_insights_hour",
    "dim_fin_currency_info_hourly",
)
ROOT_CHECKER_NAME = "dmr_pub_column_check"
STANDARD_DEV_SCHEMA = "giikin_develop"


def build_standard_material_report_ods_artifacts(
    *,
    ods_table: str = MATERIAL_REPORT_ODS_TABLE,
    oss_path: str,
    file_format: str = "json",
    dev_schema: str | None = None,
    prod_schema: str = "giikin",
    ods_sql_directory: str,
) -> dict[str, Any]:
    """Build the fixed raw-JSON ODS DDL and import SQL for the standard source."""
    from dataworks_agent.services.ods_oss.config import build_oss_import_sql, normalize_file_format

    if ods_table != MATERIAL_REPORT_ODS_TABLE:
        raise ValueError(
            f"Standard OSS path only supports {MATERIAL_REPORT_ODS_TABLE}, got {ods_table!r}"
        )
    if not str(ods_sql_directory or "").strip():
        raise ValueError("Standard OSS path requires ods_sql_directory")
    assert_safe_table_name(ods_table)
    dev_schema = str(dev_schema or STANDARD_DEV_SCHEMA).strip()
    prod_schema = str(prod_schema or "giikin").strip()
    assert_safe_table_name(dev_schema)
    assert_safe_table_name(prod_schema)
    normalized_format = normalize_file_format(file_format) or "json"
    if normalized_format != "json":
        raise ValueError("Standard TikTok material report ODS only supports JSON")

    ddl_body = (
        f"CREATE TABLE IF NOT EXISTS {{schema}}.{ods_table} (\n"
        "  `json_data` STRING COMMENT 'OSS JSON raw record'\n"
        ") COMMENT 'TikTok Smart Plus material report raw JSON ODS'\n"
        "PARTITIONED BY (`dt` STRING, `ht` STRING);"
    )
    sql = build_oss_import_sql(
        target_table=ods_table,
        oss_path=oss_path,
        file_format=normalized_format,
        schedule_type="hour",
        raw_json_text=True,
    )
    return {
        "ods_table": ods_table,
        "file_format": normalized_format,
        "oss_path": oss_path,
        "ods_sql_directory": ods_sql_directory,
        "environment_artifacts": {
            "dev": {
                "schema": dev_schema,
                "ddl": ddl_body.replace("{schema}", dev_schema),
                "status": "draft",
            },
            "prod": {
                "schema": prod_schema,
                "ddl": ddl_body.replace("{schema}", prod_schema),
                "status": "approval_required",
            },
        },
        "ddl": ddl_body.replace("{schema}", dev_schema),
        "sql": sql,
        "ingestion_mode": "raw_json_text",
        "schedule": {
            "cycle": "hourly",
            "parameters": list(MATERIAL_REPORT_SCHEDULE_PARAMETERS),
        },
    }


@dataclass(frozen=True)
class JsonFieldMapping:
    json_key: str
    target_name: str
    type: str = "STRING"
    comment: str = ""


def is_standard_material_report(params: dict[str, Any]) -> bool:
    ods_table = str(params.get("ods_table") or params.get("source_table") or "").strip()
    oss_path = str(params.get("oss_path") or "").strip()
    # A path-only OSS request still has enough information to select the
    # standard flow. Match the final directory exactly; do not classify every
    # OSS source as this one.
    oss_object_name = oss_path.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return (
        ods_table == MATERIAL_REPORT_ODS_TABLE
        or oss_object_name == "tiktok_smart_plus_material_report"
        or bool(params.get("standard_oss_json"))
        or str(params.get("template_task_id") or params.get("task_id") or "")
        == MATERIAL_REPORT_TEMPLATE_TASK_ID
    )


def normalize_json_field_mappings(raw: Any) -> list[JsonFieldMapping]:
    if not isinstance(raw, list):
        return []
    mappings: list[JsonFieldMapping] = []
    seen_targets: set[str] = set()
    seen_keys: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        json_key = str(
            item.get("json_key") or item.get("source_key") or item.get("source_field_name") or ""
        ).strip()
        target_name = str(
            item.get("target_name") or item.get("target_field_name") or item.get("name") or ""
        ).strip()
        if not json_key or not target_name:
            continue
        if json_key in seen_keys or target_name in seen_targets:
            raise ValueError(f"JSON field mapping duplicated: {json_key!r} -> {target_name!r}")
        if "'" in json_key or "\n" in json_key or "\r" in json_key:
            raise ValueError(f"JSON key contains illegal characters: {json_key!r}")
        assert_safe_table_name(target_name)
        seen_keys.add(json_key)
        seen_targets.add(target_name)
        mappings.append(
            JsonFieldMapping(
                json_key=json_key,
                target_name=target_name,
                type=str(item.get("type") or item.get("data_type") or "STRING").upper(),
                comment=str(item.get("comment") or item.get("description") or ""),
            )
        )
    return mappings


def _normalize_keys(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace("?", ",").split(",")]
    if not isinstance(raw, (list, tuple, set)):
        return []
    keys: list[str] = []
    for value in raw:
        name = str(value or "").strip()
        if name and name not in keys:
            assert_safe_table_name(name)
            keys.append(name)
    return keys


def candidate_logical_primary_keys(
    columns: list[dict[str, Any]] | list[str],
    data_profile: dict[str, Any] | None = None,
) -> list[list[str]]:
    """Return candidates from observed fields; never invent fields from the template."""
    names = [str(item.get("name") if isinstance(item, dict) else item).strip() for item in columns]
    names = [name for name in names if name]
    profile = data_profile or {}
    distinct = profile.get("distinct_counts") or {}
    record_count = int(profile.get("record_count") or 0)

    scored: list[tuple[int, str]] = []
    for name in names:
        lower = name.lower()
        score = 0
        if lower == "id" or lower.endswith("_id"):
            score += 30
        if lower.endswith("_code") or lower.endswith("_key"):
            score += 20
        if record_count and distinct.get(name) == record_count:
            score += 40
        if score:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    candidates = [[name] for _, name in scored[:5]]
    if len(scored) >= 2:
        pair = [name for _, name in scored[:2]]
        if pair not in candidates:
            candidates.append(pair)
    return candidates


def _qualified_ddl(ddl: str, schema: str, table: str) -> str:
    marker = f"create table {table}"
    qualified = f"create table {schema}.{table}"
    return ddl.replace(marker, qualified, 1).replace(
        f"drop table if exists {table}", f"drop table if exists {schema}.{table}", 1
    )


def build_standard_material_report_artifacts(
    *,
    field_mappings: Any,
    dwd_table: str = MATERIAL_REPORT_DWD_TABLE,
    ods_table: str = MATERIAL_REPORT_ODS_TABLE,
    template_task_id: str = MATERIAL_REPORT_TEMPLATE_TASK_ID,
    schedule_minute: int = 3,
    dev_schema: str | None = None,
    prod_schema: str = "giikin",
    granularity: str = "hour",
    logical_primary_keys: Any = None,
    data_profile: dict[str, Any] | None = None,
    ods_sql_directory: str | None = None,
    dwd_sql_directory: str | None = None,
) -> dict[str, Any]:
    if ods_table != MATERIAL_REPORT_ODS_TABLE:
        raise ValueError(
            f"Standard OSS path only supports {MATERIAL_REPORT_ODS_TABLE}, got {ods_table!r}"
        )
    dwd_table = str(dwd_table or MATERIAL_REPORT_DWD_TABLE).strip()
    assert_safe_table_name(ods_table)
    assert_safe_table_name(dwd_table)
    dev_schema = str(dev_schema or STANDARD_DEV_SCHEMA).strip()
    prod_schema = str(prod_schema or "giikin").strip()
    assert_safe_table_name(dev_schema)
    assert_safe_table_name(prod_schema)
    granularity = str(granularity or "hour").lower()
    if granularity not in {"hour", "day"}:
        raise ValueError("granularity must be hour or day")

    mappings = normalize_json_field_mappings(field_mappings)
    if not mappings:
        raise ValueError("Standard OSS path requires explicit json_field_mappings")
    profile = dict(data_profile or {})
    observed_columns = profile.get("columns") or [
        {"name": mapping.json_key, "type": mapping.type} for mapping in mappings
    ]
    candidates = candidate_logical_primary_keys(observed_columns, profile)
    logical_keys = _normalize_keys(logical_primary_keys)
    partition_fields = ["dt", "ht"] if granularity == "hour" else ["dt"]
    partition_parameters = list(
        MATERIAL_REPORT_SCHEDULE_PARAMETERS if granularity == "hour" else ("gmtdate",)
    )

    target_fields = [
        {
            "name": mapping.target_name,
            "type": mapping.type,
            "comment": mapping.comment or mapping.target_name,
        }
        for mapping in mappings
    ]
    target_fields.extend(
        {"name": name, "type": "STRING", "comment": "business partition"}
        for name in partition_fields
    )
    structured_metadata = {
        "targets": [
            {
                "table_name": dwd_table,
                "table_comment": "TikTok Smart Plus material report JSON DWD",
                "update_mode": "hourly" if granularity == "hour" else "daily",
                "partition_fields": partition_fields,
                "logical_primary_keys": logical_keys,
                "fields": target_fields,
            }
        ],
        "sources": [{"table_name": ods_table, "alias": "t1", "is_master": True}],
        "field_mappings": [
            {
                "source_alias": "t2",
                "source_field_name": f"j{index}",
                "target_field_name": mapping.target_name,
                "json_key": mapping.json_key,
                "field_category": "json_tuple",
                "apply_coalesce": False,
            }
            for index, mapping in enumerate(mappings, start=1)
        ],
        "joins": [],
    }
    ddl = DwdDDLGenerator().generate(
        DwdDDLGenerator().from_structured_metadata(structured_metadata)
    )
    json_keys = ",\n    ".join(f"'{mapping.json_key}'" for mapping in mappings)
    aliases = ",\n    ".join(f"j{index}" for index in range(1, len(mappings) + 1))
    select_fields = ",\n    ".join(
        f"t2.j{index} AS {mapping.target_name}" for index, mapping in enumerate(mappings, start=1)
    )
    partition_expr = ", ".join(
        f"{name} = '${{{'gmtdate' if name == 'dt' else 'hour_last1h'}}}'"
        for name in partition_fields
    )
    where_expr = " AND ".join(
        f"t1.{name} = '${{{'gmtdate' if name == 'dt' else 'hour_last1h'}}}'"
        for name in partition_fields
    )
    sql_body = (
        f"INSERT OVERWRITE TABLE {{schema}}.{dwd_table} PARTITION ({partition_expr})\n"
        f"SELECT\n    {select_fields}\n"
        f"FROM {{schema}}.{ods_table} t1\n"
        f"LATERAL VIEW OUTER JSON_TUPLE(\n    t1.json_data,\n    {json_keys}\n) t2 AS\n    {aliases}\n"
        f"WHERE {where_expr};"
    )
    sql = sql_body.replace("{schema}", dev_schema)

    root_result = RootChecker().check_fields_local([mapping.target_name for mapping in mappings])
    ddl_result = check_ddl(ddl)
    validation = {
        "passed": root_result.passed and ddl_result.passed,
        "checker": ROOT_CHECKER_NAME,
        "root_check": root_result.model_dump(),
        "ddl_check": {
            "table_name": ddl_result.table_name,
            "passed": ddl_result.passed,
            "errors": ddl_result.errors,
            "warnings": ddl_result.warnings,
        },
        "root_source": root_result.source,
    }
    if root_result.source != "online":
        validation["warning"] = "online root dictionary is unavailable"

    cron = MATERIAL_REPORT_TEMPLATE_CRON if granularity == "hour" else "00 03 03 * * ?"
    schedule = {
        "cycle": "hourly" if granularity == "hour" else "daily",
        "cron": cron,
        "minute": schedule_minute,
        "parameters": partition_parameters,
        "template_task_id": template_task_id,
        "template_node": MATERIAL_REPORT_TEMPLATE_NODE,
    }
    dependency_plan = {
        "mode": "dry_run_plan",
        "upstream_refs": [f"{dev_schema}.{ods_table}"],
        "target_output": f"{dev_schema}.{dwd_table}",
        "flow_depends": [
            {
                "type": "Normal",
                "sourceType": "Manual",
                "output": f"{dev_schema}.{ods_table}",
                "refTableName": f"{dev_schema}.{ods_table}",
            }
        ],
        "self_dependency": {"type": "CrossCycleDependsOnSelf"},
        "dev_schema": dev_schema,
        "template_task_id": template_task_id,
        "template_parent_references": list(MATERIAL_REPORT_TEMPLATE_PARENT_REFERENCES),
        "template_parent_references_are_reference_only": True,
    }
    return {
        "standard": "tiktok_smart_plus_material_report",
        "dev_schema": dev_schema,
        "prod_schema": prod_schema,
        "qualified_ods_table": f"{dev_schema}.{ods_table}",
        "qualified_dwd_table": f"{dev_schema}.{dwd_table}",
        "ods_table": ods_table,
        "dwd_table": dwd_table,
        "template_task_id": template_task_id,
        "template_node": MATERIAL_REPORT_TEMPLATE_NODE,
        "field_mappings": [mapping.__dict__ for mapping in mappings],
        "data_profile": profile,
        "candidate_logical_primary_keys": candidates,
        "logical_primary_keys": logical_keys,
        "granularity": granularity,
        "ods_sql_directory": ods_sql_directory,
        "dwd_sql_directory": dwd_sql_directory,
        "structured_metadata": structured_metadata,
        "ddl": ddl,
        "sql": sql,
        "environment_artifacts": {
            "dev": {
                "schema": dev_schema,
                "ddl": _qualified_ddl(ddl, dev_schema, dwd_table),
                "sql": sql,
                "status": "draft",
            },
            "prod": {
                "schema": prod_schema,
                "ddl": _qualified_ddl(ddl, prod_schema, dwd_table),
                "sql": sql_body.replace("{schema}", prod_schema),
                "status": "approval_required",
            },
        },
        "schedule": schedule,
        "dependency_plan": dependency_plan,
        "validation": validation,
    }

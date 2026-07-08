"""Pure DI configuration builders (from data-development-design ods_di_pipeline)."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from dataworks_agent.services.ods_di.constants import (
    INIT_PARTITION_DATE,
    INIT_PARTITION_HOUR,
)
from dataworks_agent.services.ods_di.ddl_parser import DDLParseError, DDLParser

logger = logging.getLogger(__name__)

SOURCE_TYPE_PREFIXES = {
    "mysql": "mysql",
    "oss": "oss",
    "hologres": "hologres",
    "maxcompute": "odps",
    "odps": "odps",
    "polardb": "polardb",
    "polar": "polardb",
    "postgresql": "postgresql",
    "postgres": "postgresql",
}


def resolve_source_step_type(source_type: str | None) -> str:
    """Map DataWorks datasource type to DI reader stepType."""
    normalized = (source_type or "mysql").strip().lower()
    return SOURCE_TYPE_PREFIXES.get(normalized, normalized or "mysql")


def infer_split_pk(columns: list[dict[str, Any]], source_table_name: str) -> str:
    """Identify split_pk from column metadata."""
    col_map = {c["column_name"]: c for c in columns}

    for col in columns:
        if col.get("column_key", "").upper() == "PRI":
            return col["column_name"]

    for candidate in ("id", "pk", f"{source_table_name}_id"):
        if candidate in col_map:
            return candidate

    logger.warning("未识别到 split_pk，使用空字符串")
    return ""


def build_where_clause(where_type: str, where_field: str, granularity: str) -> str:
    """Generate incremental WHERE clause for the DI reader."""
    if not where_field:
        return ""

    if granularity == "hour":
        if where_type == "unix":
            return f"{where_field} >= unix_timestamp('${{gmtdate_last2h}} ${{hour_last2h}}:00:00')"
        return f"{where_field} >= '${{gmtdate_last2h}} ${{hour_last2h}}:00:00'"

    return (
        f"{where_field} >= '${{bizdate}}' AND "
        f"{where_field} < date_add('${{bizdate}}', interval 1 day)"
    )


def build_business_partition(granularity: str) -> str:
    """Return normal scheduled partition (not init partition)."""
    partition = (
        "dt=${gmtdate},ht=${hour_last1h}" if granularity in {"hour", "hourly"} else "dt=${bizdate}"
    )
    if INIT_PARTITION_DATE in partition:
        raise ValueError("normal task must not write the initialization partition")
    return partition


def build_init_partition(
    granularity: str,
    *,
    init_partition_date: str = INIT_PARTITION_DATE,
    init_partition_hour: str = INIT_PARTITION_HOUR,
) -> str:
    """Return fixed partition for first-time initialization."""
    if granularity in {"hour", "hourly"}:
        return f"dt={init_partition_date},ht={init_partition_hour}"
    if granularity in {"day", "all"}:
        return f"dt={init_partition_date}"
    raise ValueError(f"unsupported initialization granularity: {granularity}")


def build_di_task_config(
    datasource_name: str,
    source_table_name: str,
    ods_table_name: str,
    columns: list[str],
    odps_datasource_name: str,
    granularity: str = "hour",
    split_pk: str = "id",
    where_type: str = "none",
    where_field: str = "",
    source_step_type: str = "mysql",
    task_role: Literal["init", "incremental"] = "incremental",
    init_partition_date: str = INIT_PARTITION_DATE,
    init_partition_hour: str = INIT_PARTITION_HOUR,
) -> dict[str, Any]:
    """Build wizard-mode DI config for a business table sync task."""
    where_clause = (
        "" if task_role == "init" else build_where_clause(where_type, where_field, granularity)
    )
    partition = (
        build_init_partition(
            granularity,
            init_partition_date=init_partition_date,
            init_partition_hour=init_partition_hour,
        )
        if task_role == "init"
        else build_business_partition(granularity)
    )

    return {
        "transform": False,
        "type": "job",
        "version": "2.0",
        "steps": [
            {
                "stepType": source_step_type,
                "parameter": {
                    "partitionKey": None,
                    "envType": 1,
                    "useSpecialSecret": False,
                    "column": columns,
                    "where": where_clause,
                    "connection": [
                        {
                            "datasource": datasource_name,
                            "table": [source_table_name],
                        }
                    ],
                    "splitPk": split_pk,
                    "encoding": "UTF-8",
                },
                "name": "Reader",
                "category": "reader",
            },
            {
                "copies": 1,
                "parameter": {"nodes": [], "edges": [], "groups": [], "version": "2.0"},
                "name": "Processor",
                "category": "processor",
            },
            {
                "stepType": "odps",
                "parameter": {
                    "partition": partition,
                    "truncate": True,
                    "partitionKey": None,
                    "datasource": odps_datasource_name,
                    "envType": 1,
                    "tunnelQuota": "default",
                    "isSupportThreeModel": False,
                    "column": columns,
                    "emptyAsNull": False,
                    "table": ods_table_name,
                    "consistencyCommit": False,
                },
                "name": "Writer",
                "category": "writer",
            },
        ],
        "setting": {
            "executeMode": None,
            "failoverEnable": None,
            "errorLimit": {"record": "0"},
            "speed": {"concurrent": 2, "throttle": False},
        },
        "order": {"hops": [{"from": "Reader", "to": "Writer"}]},
        "extend": {
            "mode": "wizard",
            "resourceGroup": "",
            "cu": 0.5,
            "oneStopPageNum": 1,
            "formatType": "datax",
        },
    }


def inject_schema_prefix_in_ddl(ddl_text: str, mc_project: str) -> str:
    """Prefix bare CREATE TABLE targets with the MaxCompute project name."""
    if not mc_project:
        return ddl_text

    return re.sub(
        r"(?i)(CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)(`?)(\w+(?:\.\w+)?)(`?)(\s*\()",
        lambda m: (
            m.group(0)
            if "." in m.group(3)
            else f"{m.group(1)}{m.group(2)}{mc_project}.{m.group(3)}{m.group(4)}{m.group(5)}"
        ),
        ddl_text,
        count=1,
    )


def strip_leading_drop_table(ddl: str) -> str:
    """去掉建表 DDL 开头的 `drop table if exists ...;`。

    建表仅在表不存在时执行，DROP 冗余；MaxCompute execute_ddl 经 DestructiveOpGuard
    会拦 DROP TABLE（非 tmp_/test_），故剥离后只跑 CREATE。
    """
    return re.sub(
        r"^\s*drop\s+table\s+if\s+exists\s+[^;]+;\s*", "", ddl, count=1, flags=re.IGNORECASE
    )


def sql_literal(value: str) -> str:
    """Return a single-quoted SQL literal with embedded quotes escaped."""
    return "'" + value.replace("'", "''") + "'"


def compare_ddl_structures(expected_ddl: str, actual_ddl: str) -> dict[str, Any]:
    """Compare field names/types, including partition fields parsed from DDL."""
    parser = DDLParser()
    try:
        expected = parser.parse(expected_ddl)
        actual = parser.parse(actual_ddl)
    except DDLParseError as exc:
        return {"compatible": False, "differences": [f"ddl_parse_error: {exc}"]}

    def signature(structure: Any) -> dict[str, str]:
        return {
            field.name.lower(): re.sub(r"\s+", "", field.type.upper()) for field in structure.fields
        }

    expected_fields = signature(expected)
    actual_fields = signature(actual)
    differences: list[str] = []
    for name, expected_type in expected_fields.items():
        actual_type = actual_fields.get(name)
        if actual_type is None:
            differences.append(f"missing_field:{name}")
        elif actual_type != expected_type:
            differences.append(f"type_mismatch:{name}:{expected_type}!={actual_type}")
    for name in actual_fields.keys() - expected_fields.keys():
        differences.append(f"unexpected_field:{name}")
    return {"compatible": not differences, "differences": sorted(differences)}


def extract_non_partition_columns_from_ddl(ddl_text: str) -> list[str]:
    """Extract non-partition column names from a MaxCompute CREATE TABLE DDL."""
    parser = DDLParser()
    structure = parser.parse(ddl_text)
    return [
        field.name.lower()
        for field in structure.fields
        if field.name.lower() not in {"dt", "ht", "mt"}
    ]


def build_node_name(ods_table_name: str, task_role: Literal["init", "incremental"]) -> str:
    """Return DataWorks node name for init or incremental task."""
    return f"{ods_table_name}_init" if task_role == "init" else ods_table_name


def build_first_incremental_where_clause(
    where_type: str,
    where_field: str,
    granularity: str,
    lookback_hours: int,
) -> str:
    """Generate expanded WHERE for the first incremental run."""
    if not where_field:
        return ""
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")

    seconds = lookback_hours * 3600
    anchor = (
        "'${gmtdate} ${hour_last1h}:00:00'"
        if granularity in {"hour", "hourly"}
        else "'${bizdate} 00:00:00'"
    )
    if where_type == "unix":
        return f"{where_field} >= unix_timestamp({anchor}) - {seconds}"
    return f"{where_field} >= from_unixtime(unix_timestamp({anchor}) - {seconds})"


def build_copy_init_partition_sql(
    *,
    ods_table_name: str,
    columns: list[str],
    granularity: str,
    ddl: str | None = None,
    dev_project: str = "dataworks_dev",
    prod_project: str = "dataworks",
    init_partition_date: str = INIT_PARTITION_DATE,
    init_partition_hour: str = INIT_PARTITION_HOUR,
) -> str:
    """Build SQL copying init partition from dev to prod."""
    ddl_columns: list[str] = []
    if ddl:
        try:
            ddl_columns = extract_non_partition_columns_from_ddl(ddl)
        except DDLParseError:
            ddl_columns = []

    non_partition_columns = ddl_columns or [
        column for column in columns if column.lower() not in {"dt", "ht", "mt"}
    ]
    if not non_partition_columns:
        raise ValueError("copy SQL requires at least one non-partition column")

    select_columns = ",\n    ".join(non_partition_columns)
    if granularity in {"hour", "hourly"}:
        partition = f"dt='{init_partition_date}', ht='{init_partition_hour}'"
        where = f"dt='{init_partition_date}'\n  AND ht='{init_partition_hour}'"
    elif granularity in {"day", "all"}:
        partition = f"dt='{init_partition_date}'"
        where = f"dt='{init_partition_date}'"
    else:
        raise ValueError(f"unsupported initialization granularity: {granularity}")

    return (
        f"INSERT OVERWRITE TABLE {prod_project}.{ods_table_name}\n"
        f"PARTITION ({partition})\n"
        "SELECT\n"
        f"    {select_columns}\n"
        f"FROM {dev_project}.{ods_table_name}\n"
        f"WHERE {where};"
    )


def replace_reader_where(di_config: dict[str, Any], where_clause: str) -> dict[str, Any]:
    """Return a DI config copy with Reader parameter.where replaced."""
    import json

    cloned = json.loads(json.dumps(di_config, ensure_ascii=False))
    for step in cloned.get("steps") or []:
        if step.get("category") == "reader" or step.get("name") == "Reader":
            step.setdefault("parameter", {})["where"] = where_clause
            return cloned
    raise ValueError("DI config reader step not found")


def partition_where_clause(
    granularity: str,
    *,
    init_partition_date: str = INIT_PARTITION_DATE,
    init_partition_hour: str = INIT_PARTITION_HOUR,
) -> str:
    """SQL WHERE fragment for the fixed init partition."""
    if granularity in {"hour", "hourly"}:
        return f"dt='{init_partition_date}' AND ht='{init_partition_hour}'"
    return f"dt='{init_partition_date}'"


def evaluate_publish_gate(
    *,
    tables_created: bool,
    init_run_succeeded: bool,
    dev_validated: bool,
    prod_copy_succeeded: bool,
    prod_validated: bool,
    incremental_filter_valid: bool,
) -> dict[str, Any]:
    """Return every unmet condition that blocks incremental publication."""
    conditions = {
        "tables_not_created": tables_created,
        "init_run_failed": init_run_succeeded,
        "dev_not_validated": dev_validated,
        "prod_copy_failed": prod_copy_succeeded,
        "prod_not_validated": prod_validated,
        "incremental_filter_invalid": incremental_filter_valid,
    }
    unmet = [name for name, passed in conditions.items() if not passed]
    return {"allowed": not unmet, "unmet_conditions": unmet}

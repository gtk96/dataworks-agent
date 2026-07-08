"""Pure SQL/DDL lineage parsing helpers (from data-development-design)."""

from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlglot import exp

from dataworks_agent.services.ods_di.ddl_parser import DDLParseError, DDLParser

logger = logging.getLogger(__name__)


def parse_ddl_structure(ddl_text: str) -> dict[str, Any]:
    """Parse CREATE TABLE DDL into columns and partition fields."""
    try:
        structure = DDLParser().parse(ddl_text)
        fields = [
            {"name": field.name, "type": field.type, "comment": field.comment}
            for field in structure.fields
        ]
        partition_names = _extract_partition_names(ddl_text)
        partitions = [field for field in fields if field["name"] in partition_names]
        columns = [field for field in fields if field["name"] not in partition_names]
        return {
            "table_name": structure.table_name,
            "columns": columns,
            "partitions": partitions,
            "parse_state": "ok",
            "parse_error": None,
        }
    except (DDLParseError, Exception) as exc:
        logger.warning("解析 DDL 失败: %s", exc)
        return {
            "table_name": None,
            "columns": [],
            "partitions": [],
            "parse_state": "parse_failed",
            "parse_error": str(exc),
        }


def extract_source_tables(sql_code: str) -> list[str]:
    """Extract distinct source table names from SQL."""
    parsed = _parse_sql(sql_code)
    if parsed is None:
        return []

    targets = {
        table.name.lower()
        for statement in parsed
        for table in statement.find_all(exp.Table)
        if _is_write_target(table)
    }
    tables: list[str] = []
    seen: set[str] = set()
    for statement in parsed:
        for table in statement.find_all(exp.Table):
            name = _table_name(table)
            key = name.lower()
            if key in targets or key in seen:
                continue
            seen.add(key)
            tables.append(name)
    return tables


def parse_sql_lineage(sql_code: str) -> dict[str, Any]:
    """Parse SQL source tables and JOIN metadata."""
    parsed = _parse_sql(sql_code)
    if parsed is None:
        return {"source_tables": [], "joins": [], "parse_state": "parse_failed"}

    joins: list[dict[str, str | None]] = []
    for statement in parsed:
        for join in statement.find_all(exp.Join):
            table = join.find(exp.Table)
            if table is None:
                continue
            joins.append(
                {
                    "table": _table_name(table),
                    "join_type": (join.args.get("kind") or "").upper() or None,
                    "on": join.args.get("on").sql(dialect="hive") if join.args.get("on") else None,
                }
            )

    return {
        "source_tables": extract_source_tables(sql_code),
        "joins": joins,
        "parse_state": "ok",
    }


def is_temp_table(table_name: str) -> bool:
    return table_name.split(".")[-1].lower().startswith("tmp_")


def _parse_sql(sql_code: str) -> list[exp.Expression] | None:
    if not sql_code or not sql_code.strip():
        return []
    try:
        return sqlglot.parse(sql_code, read="hive", error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as exc:
        logger.warning("解析 SQL 血缘失败: %s", exc)
        return None


def _table_name(table: exp.Table) -> str:
    name = table.name
    if table.db:
        return f"{table.db}.{name}"
    return name


def _is_write_target(table: exp.Table) -> bool:
    parent = table.parent
    while parent is not None:
        if isinstance(parent, (exp.Insert, exp.Create)):
            return parent.this is table or table in list(parent.find_all(exp.Table))[:1]
        parent = parent.parent
    return False


def _extract_partition_names(ddl_text: str) -> set[str]:
    marker = "PARTITIONED BY"
    upper = ddl_text.upper()
    idx = upper.find(marker)
    if idx < 0:
        return set()
    block = ddl_text[idx + len(marker) :]
    start = block.find("(")
    end = block.find(")")
    if start < 0 or end <= start:
        return set()
    names = set()
    for part in block[start + 1 : end].split(","):
        token = part.strip().split()
        if token:
            names.add(token[0].strip('`"').lower())
    return names

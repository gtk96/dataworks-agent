"""Load ODS column metadata from local dw-modeling-template SQL or existing MC ODS tables."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.naming import generate_ods_di_table_name
from dataworks_agent.services.ods_di.ddl_parser import DDLParseError, DDLParser

logger = logging.getLogger(__name__)

PARTITION_NAMES = frozenset({"dt", "ht", "mt", "update_ht"})


def _structure_to_rows(structure: Any) -> list[dict[str, Any]]:
    return [
        {
            "column_name": field.name,
            "data_type": field.type.lower(),
            "column_key": "PRI" if field.name.lower() == "id" else "",
            "column_position": index,
        }
        for index, field in enumerate(structure.fields, start=1)
        if field.name.lower() not in PARTITION_NAMES
    ]


def parse_ods_ddl_columns(ddl_text: str) -> list[dict[str, Any]] | None:
    try:
        structure = DDLParser().parse(ddl_text)
    except DDLParseError as exc:
        logger.debug("Local/MC DDL parse failed: %s", exc)
        return None
    rows = _structure_to_rows(structure)
    return rows or None


def extract_create_table_ddl(content: str, table_bare: str) -> str | None:
    """Extract one CREATE TABLE block for table_bare from a multi-table DDL file."""
    pattern = re.compile(
        rf"create\s+table\s+(?:[\w.]+\.)?{re.escape(table_bare)}\s*\(",
        re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        return None

    depth = 0
    idx = match.end() - 1
    while idx < len(content):
        char = content[idx]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = idx + 1
                tail = content[end : end + 400]
                part_match = re.match(
                    r"\s*partitioned\s+by\s*\([^)]+\)",
                    tail,
                    re.IGNORECASE | re.DOTALL,
                )
                if part_match:
                    end += part_match.end()
                return content[match.start() : end].strip()
        idx += 1
    return None


def find_local_ods_ddl(
    holo_schema: str,
    source_table: str,
    granularity: str,
    *,
    template_root: str | None = None,
) -> str | None:
    root = Path(template_root or settings.sql_template_root)
    if not root.is_dir():
        return None

    ods_table = generate_ods_di_table_name(
        holo_schema, source_table, granularity, source_type="hologres"
    )
    source_tag = f"{holo_schema}.{source_table}".lower()

    for path in sorted(root.rglob("ods/ddl/*.sql")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lowered = text.lower()
        if ods_table not in lowered and source_tag not in lowered:
            continue
        ddl = extract_create_table_ddl(text, ods_table)
        if ddl:
            logger.info("本地 ODS DDL 命中: %s (%s)", ods_table, path)
            return ddl
    return None


def query_columns_from_local_template(
    holo_schema: str,
    source_table: str,
    granularity: str,
) -> list[dict[str, Any]] | None:
    ddl = find_local_ods_ddl(holo_schema, source_table, granularity)
    if not ddl:
        return None
    return parse_ods_ddl_columns(ddl)


async def query_columns_from_mc_ods_ddl(
    bff: Any,
    mcp: Any,
    holo_schema: str,
    source_table: str,
    granularity: str,
) -> list[dict[str, Any]] | None:
    """Parse columns from dataworks/dataworks_dev ODS table if already created."""
    from dataworks_agent.state import app_state

    mc = getattr(app_state, "_maxcompute_client", None)
    ods_table = generate_ods_di_table_name(
        holo_schema, source_table, granularity, source_type="hologres"
    )
    projects = [settings.dataworks_prod_schema, settings.dataworks_dev_schema]

    for project in projects:
        table_guid = f"odps.{project}.{ods_table}"
        ddl: str | None = None
        # AK/SK MaxCompute 优先取现有表 DDL（不依赖 DataMap 权限）
        if mc is not None:
            try:
                ddl = await mc.get_table_ddl(ods_table, project=project)
            except Exception as exc:
                logger.debug("MaxCompute get_table_ddl %s: %s", table_guid, exc)

        if not ddl:
            try:
                ddl = await bff.get_creation_ddl(table_guid)
            except Exception as exc:
                logger.debug("BFF geneCreationDdl %s: %s", table_guid, exc)

        if (not ddl or "CREATE TABLE" not in ddl.upper()) and mcp is not None:
            try:
                raw = await mcp.call_tool("get_table_ddl", {"table_guid": table_guid})
                if raw:
                    ddl = str(raw)
            except Exception as exc:
                logger.debug("MCP get_table_ddl %s: %s", table_guid, exc)

        if not ddl or "CREATE TABLE" not in ddl.upper():
            continue

        rows = parse_ods_ddl_columns(str(ddl))
        if rows:
            logger.info("MC ODS DDL 命中: %s", table_guid)
            return rows
    return None

"""Generate production-grade Holo ODS DML (cda 外表 ← Holo 原生 schema)."""

from __future__ import annotations

import logging
import re
from typing import Any

from dataworks_agent.naming.schedule import DAILY_SQL_PARAMETERS, HOURLY_SQL_PARAMETERS
from dataworks_agent.services.ods_di.where_infer import infer_incremental_where
from dataworks_agent.services.ods_holo.column_resolver import load_holo_ods_columns

logger = logging.getLogger(__name__)


class OdsMetadataMissingError(ValueError):
    """Raised when Holo ODS DML cannot list columns explicitly (select * forbidden)."""

    def __init__(self, holo_schema: str, source_table: str) -> None:
        self.holo_schema = holo_schema
        self.source_table = source_table
        super().__init__(
            f"无法解析 {holo_schema}.{source_table} 的字段元数据，"
            "禁止生成 select * DML。"
            "请确认 Holo 表可读、仓库 DDL registry 已收录，或先在 DataWorks 补全 ODS DDL。"
        )


PARTITION_FIELDS = frozenset({"dt", "ht", "mt"})
TIME_NAME_PATTERN = re.compile(
    r"(^gmt_(create|modify|update)$|_(time|at)$|^(create|update|modify|payment|purchase|delivery|deal)_time$)",
    re.IGNORECASE,
)
TIMESTAMP_TYPES = frozenset({"timestamp", "timestamptz", "datetime", "date"})


def _is_time_like(name: str, data_type: str) -> bool:
    lowered = name.lower()
    if lowered in PARTITION_FIELDS or lowered == "update_ht":
        return False
    if any(t in data_type.lower() for t in TIMESTAMP_TYPES):
        return True
    return bool(TIME_NAME_PATTERN.search(lowered))


def _select_expr(column_name: str, source_meta: dict[str, str]) -> str:
    meta_type = source_meta.get(column_name.lower(), "")
    if _is_time_like(column_name, meta_type):
        return f"{column_name}::text"
    return column_name


def _resolve_where_clause(
    source_columns: list[dict[str, Any]],
    granularity: str,
    where_mode: str = "auto",
) -> str:
    return infer_incremental_where(source_columns, granularity, where_mode).get("where_clause", "")


def _partition_literals(granularity: str) -> tuple[str, str, str]:
    gran = granularity.lower()
    if gran in {"hour", "hourly", "min"}:
        return (
            "'${gmtdate}${hour_last1h}' as update_ht",
            "'${gmtdate}' as dt",
            "'${hour_last1h}' as ht",
        )
    return ("", "'${bizdate}' as dt", "")


async def _load_source_columns(
    bff: Any,
    mcp: Any,
    holo_schema: str,
    source_table: str,
    granularity: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (column metadata rows, ordered ODS target column names)."""
    resolved = await load_holo_ods_columns(bff, mcp, holo_schema, source_table, granularity)
    return resolved.get("source_columns") or [], resolved.get("target_columns") or []


def _render_dml(
    *,
    holo_schema: str,
    source_table: str,
    target_table: str,
    target_columns: list[str],
    source_meta: dict[str, str],
    granularity: str,
    where_clause: str,
) -> str:
    update_ht_expr, dt_expr, ht_expr = _partition_literals(granularity)
    select_lines: list[str] = []

    for col in target_columns:
        lowered = col.lower()
        if lowered == "update_ht" and update_ht_expr:
            select_lines.append(f"    {update_ht_expr}")
        elif lowered == "dt" and dt_expr:
            select_lines.append(f"    {dt_expr}")
        elif lowered == "ht" and ht_expr:
            select_lines.append(f"    {ht_expr}")
        else:
            select_lines.append(f"    {_select_expr(col, source_meta)}")

    select_body = ",\n".join(select_lines)
    header = (
        f"-- {holo_schema}.{source_table} → cda.{target_table}\n"
        f"-- Engine: Hologres (insert into cda 外表)\n"
    )
    where_sql = f"\n{where_clause}" if where_clause else ""
    import_stmt = (
        f"IMPORT FOREIGN SCHEMA dataworks\n"
        f"LIMIT TO ({target_table})\n"
        f"FROM SERVER odps_server\n"
        f"INTO cda\n"
        f"OPTIONS (if_table_exist 'update');\n\n"
    )
    return (
        f"{header}{import_stmt}insert into cda.{target_table}\n"
        f"select\n"
        f"{select_body}\n"
        f"from {holo_schema}.{source_table}{where_sql}\n"
        f";\n"
    )


def comment_out_import(dml: str) -> str:
    """Comment out the IMPORT FOREIGN SCHEMA block in DML."""
    return dml.replace("IMPORT FOREIGN SCHEMA", "-- IMPORT FOREIGN SCHEMA", 1)


# DML 文件里表段以 `-- 表名: cda.<X>` 开头。段内 `insert into cda.<X> ... ;` 之间是 DML 主体。
_DML_SECTION_HEADER = re.compile(r"^--\s*表名:\s*cda\.(\S+)\s*$", re.MULTILINE)
_DML_BODY_START = re.compile(r"insert\s+into\s+cda\.\S+\b", re.IGNORECASE)


def _strip_line_comment(line: str) -> str:
    """去除行尾 -- 注释（不在字符串字面量内；本项目 DML 字段列表不在引号内）。"""
    idx = line.find("--")
    return line[:idx].rstrip() if idx >= 0 else line.rstrip()


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    """从整份 DML 文件中抽取指定表的 DML 主体。

    旧实现用 `insert into cda.X?;` 非贪婪匹配，遇到字段列表行尾注释里的 `;`
    (例如 `-- 申请类型，1：取消申请 ;`) 会提前截断，导致 DML 缺 from/where/;。

    新实现：
    1) 先按段头 `-- 表名: cda.X` 找到本表段。
    2) 在段内从 `insert into cda.<X>` 起点开始。
    3) 去掉每行行尾 `--` 注释后，用 rfind 找末尾 `;`，避免行尾注释里的 `;` 干扰。
    """
    if not dml_content or not table_name:
        return None

    sections = list(_DML_SECTION_HEADER.finditer(dml_content))
    section_start = None
    section_end = len(dml_content)
    for i, m in enumerate(sections):
        if m.group(1) == table_name:
            section_start = m.start()
            if i + 1 < len(sections):
                section_end = sections[i + 1].start()
            break
    if section_start is None:
        return None

    seg = dml_content[section_start:section_end]
    body_match = _DML_BODY_START.search(seg)
    if not body_match:
        return None
    body = seg[body_match.start() :]

    cleaned = "\n".join(_strip_line_comment(line) for line in body.split("\n"))
    semicolon_idx = cleaned.rfind(";")
    if semicolon_idx < 0:
        return None
    return cleaned[: semicolon_idx + 1].strip()


async def build_holo_ods_dml(
    bff: Any,
    mcp: Any,
    *,
    holo_schema: str,
    source_table: str,
    target_table: str,
    granularity: str = "hour",
    where_mode: str = "auto",
) -> dict[str, Any]:
    """Build Holo ODS DML + schedule parameter set for the given granularity."""
    source_rows, target_columns = await _load_source_columns(
        bff, mcp, holo_schema, source_table, granularity
    )
    source_meta = {
        str(c.get("column_name", "")).lower(): str(c.get("data_type", "")).lower()
        for c in source_rows
    }

    if not target_columns:
        logger.error("字段元数据缺失，拒绝生成 DML: %s.%s", holo_schema, source_table)
        raise OdsMetadataMissingError(holo_schema, source_table)

    where_clause = _resolve_where_clause(source_rows, granularity, where_mode)
    dml = _render_dml(
        holo_schema=holo_schema,
        source_table=source_table,
        target_table=target_table,
        target_columns=target_columns,
        source_meta=source_meta,
        granularity=granularity,
        where_clause=where_clause,
    )
    parameters = (
        HOURLY_SQL_PARAMETERS
        if granularity.lower() in {"hour", "hourly", "min"}
        else DAILY_SQL_PARAMETERS
    )
    return {
        "dml": dml,
        "column_count": len(target_columns),
        "where_clause": where_clause,
        "parameters": parameters,
    }

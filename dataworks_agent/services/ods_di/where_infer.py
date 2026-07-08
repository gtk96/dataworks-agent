"""Incremental WHERE field / clause inference for ODS (Holo + DI)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from dataworks_agent.services.ods_di.constants import (
    DATETIME_TYPES,
    UNIX_INT_TYPES,
    WHERE_FIELD_CANDIDATES,
)

logger = logging.getLogger(__name__)


WhereMode = Literal["auto", "coalesce", "or", "modify", "create", "single", "none"]


# 生产模板常见「更新 + 创建」成对字段（对齐 order-fulfillment ODS DML）

WHERE_MODIFY_CREATE_PAIRS: list[tuple[str, str]] = [
    ("gmt_modify", "gmt_create"),
    ("update_time", "create_time"),
    ("modify_time", "create_time"),
    ("updated_at", "created_at"),
    ("gmt_modified", "gmt_create"),
    ("gmt_update", "gmt_create"),
    ("up_time", "create_time"),
    ("upd_time", "create_time"),
]


CREATE_ONLY_CANDIDATES: list[str] = [
    "create_time",
    "created_at",
    "gmt_create",
    "created_time",
    "create_at",
    "creation_time",
]


def _columns_by_lower(columns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:

    return {(c.get("column_name") or "").lower(): c for c in columns if c.get("column_name")}


def _is_unix_col(col: dict[str, Any]) -> bool:

    return str(col.get("data_type", "")).lower() in UNIX_INT_TYPES


def _find_modify_create_pair(
    columns: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:

    by_lower = _columns_by_lower(columns)

    for modify_key, create_key in WHERE_MODIFY_CREATE_PAIRS:
        mod_col = by_lower.get(modify_key)

        cre_col = by_lower.get(create_key)

        if mod_col and cre_col:
            return mod_col["column_name"], cre_col["column_name"], mod_col, cre_col

    return None


def _find_create_only(columns: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:

    by_lower = _columns_by_lower(columns)

    for create_key in CREATE_ONLY_CANDIDATES:
        col = by_lower.get(create_key)

        if col:
            return col["column_name"], col

    return None


def infer_where_field(columns: list[dict[str, Any]]) -> dict[str, str]:
    """Pick a single incremental filter column (case-insensitive)."""

    by_lower = _columns_by_lower(columns)

    for candidate in WHERE_FIELD_CANDIDATES:
        col = by_lower.get(candidate.lower())

        if not col:
            continue

        dtype = str(col.get("data_type", "")).lower()

        if dtype in DATETIME_TYPES:
            return {"where_field": col["column_name"], "where_type": "datetime"}

    for candidate in WHERE_FIELD_CANDIDATES:
        col = by_lower.get(candidate.lower())

        if not col:
            continue

        dtype = str(col.get("data_type", "")).lower()

        if dtype in UNIX_INT_TYPES:
            return {"where_field": col["column_name"], "where_type": "unix"}

    for candidate in WHERE_FIELD_CANDIDATES:
        col = by_lower.get(candidate.lower())

        if col:
            logger.warning("字段 %s 类型未知，where_type 兜底为 unix", col["column_name"])

            return {"where_field": col["column_name"], "where_type": "unix"}

    logger.warning("未找到候选 where_field，不生成增量过滤条件")

    return {"where_field": "", "where_type": "none"}


def _hour_threshold(*, unix: bool) -> str:

    if unix:
        return "unix_timestamp('${gmtdate_last2h} ${hour_last2h}:00:00')"

    return "(('${gmt_date}' || ' ' || '${hour_last2h}' || ':00:00')::timestamp at time zone 'Asia/Shanghai')"


def _day_threshold_start(*, unix: bool) -> str:

    if unix:
        return "unix_timestamp('${bizdate} 00:00:00')"

    return "'${bizdate} 00:00:00'"


def _day_threshold_end(*, unix: bool) -> str:

    if unix:
        return "unix_timestamp(date_add('${bizdate}', interval 1 day))"

    return "date_add('${bizdate}', interval 1 day)"


def _field_compare(name: str, col: dict[str, Any], *, is_hour: bool) -> str:

    unix = _is_unix_col(col)

    if is_hour:
        threshold = _hour_threshold(unix=unix)

        lhs = name if unix else f"{name}::timestamp"

        return f"{lhs} >= {threshold}"

    start = _day_threshold_start(unix=unix)

    end = _day_threshold_end(unix=unix)

    lhs = name if unix else f"{name}"

    return f"{lhs} >= {start} and {lhs} < {end}"


def _hour_filter_expr(field_expr: str, *, unix: bool) -> str:

    threshold = _hour_threshold(unix=unix)

    lhs = field_expr if unix else f"{field_expr}::timestamp"

    return f"where {lhs} >= {threshold}"


def _day_filter_expr(field_expr: str, *, unix: bool) -> str:

    start = _day_threshold_start(unix=unix)

    end = _day_threshold_end(unix=unix)

    return f"where {field_expr} >= {start} and {field_expr} < {end}"


def _wrap_where(parts: list[str]) -> str:

    return f"where {' and '.join(parts)}" if parts else ""


def list_where_options(columns: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return selectable WHERE strategies based on table columns."""

    options: list[dict[str, str]] = []

    pair = _find_modify_create_pair(columns)

    if pair:
        mod_name, cre_name, mod_col, cre_col = pair

        if not _is_unix_col(mod_col) and not _is_unix_col(cre_col):
            options.append(
                {
                    "mode": "coalesce",
                    "label": f"coalesce({mod_name}, {cre_name})",
                }
            )

        options.append({"mode": "or", "label": f"{mod_name} OR {cre_name}"})

        options.append({"mode": "modify", "label": mod_name})

        options.append({"mode": "create", "label": cre_name})

    create_only = _find_create_only(columns)

    if create_only and not any(o["mode"] == "create" for o in options):
        name, _col = create_only

        options.append({"mode": "create", "label": name})

    single = infer_where_field(columns)

    field = single.get("where_field") or ""

    if field and not any(
        o["mode"] in {"modify", "single"} and o["label"] == field for o in options
    ):
        options.append({"mode": "single", "label": field})

    options.append({"mode": "none", "label": "无增量过滤"})

    return options


def _default_where_mode(columns: list[dict[str, Any]]) -> WhereMode:

    pair = _find_modify_create_pair(columns)

    if pair:
        _mod_name, _cre_name, mod_col, cre_col = pair

        if not _is_unix_col(mod_col) and not _is_unix_col(cre_col):
            return "coalesce"

        return "or"

    if _find_create_only(columns):
        return "create"

    if infer_where_field(columns).get("where_field"):
        return "single"

    return "none"


def default_where_mode(columns: list[dict[str, Any]]) -> WhereMode:
    return _default_where_mode(columns)


def infer_incremental_where(
    columns: list[dict[str, Any]],
    granularity: str,
    where_mode: WhereMode | str = "auto",
) -> dict[str, str]:
    """Build Holo/DI incremental WHERE; mode controls coalesce / OR / single column."""

    mode: WhereMode = where_mode if where_mode != "auto" else _default_where_mode(columns)  # type: ignore[assignment]

    gran = granularity.lower()

    is_hour = gran in {"hour", "hourly", "min"}

    if mode == "none":
        return {
            "where_clause": "",
            "where_label": "",
            "where_field": "",
            "where_type": "none",
            "where_mode": mode,
        }

    pair = _find_modify_create_pair(columns)

    if pair and mode in {"coalesce", "or", "modify", "create"}:
        mod_name, cre_name, mod_col, cre_col = pair

        if mode == "coalesce":
            if _is_unix_col(mod_col) or _is_unix_col(cre_col):
                mode = "or"

            else:
                expr = f"coalesce({mod_name}, {cre_name})"

                clause = (
                    _hour_filter_expr(expr, unix=False)
                    if is_hour
                    else _day_filter_expr(expr, unix=False)
                )

                return {
                    "where_clause": clause,
                    "where_label": expr,
                    "where_field": mod_name,
                    "where_type": "coalesce_datetime",
                    "where_mode": "coalesce",
                }

        if mode == "or":
            mod_cmp = _field_compare(mod_name, mod_col, is_hour=is_hour)

            cre_cmp = _field_compare(cre_name, cre_col, is_hour=is_hour)

            label = f"{mod_name} OR {cre_name}"

            clause = _wrap_where([f"({mod_cmp} or {cre_cmp})"])

            return {
                "where_clause": clause,
                "where_label": label,
                "where_field": mod_name,
                "where_type": "or_datetime",
                "where_mode": "or",
            }

        if mode == "modify":
            cmp_expr = _field_compare(mod_name, mod_col, is_hour=is_hour)

            clause = _wrap_where([cmp_expr])

            return {
                "where_clause": clause,
                "where_label": mod_name,
                "where_field": mod_name,
                "where_type": "unix" if _is_unix_col(mod_col) else "datetime",
                "where_mode": "modify",
            }

        if mode == "create":
            cmp_expr = _field_compare(cre_name, cre_col, is_hour=is_hour)

            clause = _wrap_where([cmp_expr])

            return {
                "where_clause": clause,
                "where_label": cre_name,
                "where_field": cre_name,
                "where_type": "unix" if _is_unix_col(cre_col) else "datetime",
                "where_mode": "create",
            }

    if mode == "create":
        create_only = _find_create_only(columns)

        if create_only:
            name, col = create_only

            cmp_expr = _field_compare(name, col, is_hour=is_hour)

            clause = _wrap_where([cmp_expr])

            return {
                "where_clause": clause,
                "where_label": name,
                "where_field": name,
                "where_type": "unix" if _is_unix_col(col) else "datetime",
                "where_mode": "create",
            }

    single = infer_where_field(columns)

    field = single.get("where_field") or ""

    if not field:
        return {
            "where_clause": "",
            "where_label": "",
            "where_field": "",
            "where_type": "none",
            "where_mode": "none",
        }

    col = _columns_by_lower(columns).get(field.lower(), {})

    unix = single.get("where_type") == "unix" or _is_unix_col(col)

    clause = _hour_filter_expr(field, unix=unix) if is_hour else _day_filter_expr(field, unix=unix)

    resolved_mode: WhereMode = mode if mode == "single" else "single"

    return {
        "where_clause": clause,
        "where_label": field,
        "where_field": field,
        "where_type": "unix" if unix else "datetime",
        "where_mode": resolved_mode,
    }

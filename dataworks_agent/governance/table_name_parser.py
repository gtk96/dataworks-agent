"""Warehouse table name parsing and DataWorks metadata helpers."""

from __future__ import annotations

import re
from typing import Any

from dataworks_agent.config import settings

_LAYER_PREFIX_MAP = {
    "ods_": "ODS",
    "dwd_": "DWD",
    "dim_": "DIM",
    "dws_": "DWS",
}


def build_table_guid(table_name: str, mc_project: str | None = None) -> str:
    """Build a DataMap ODPS table guid."""
    project = mc_project or settings.dataworks_prod_schema
    clean_table = table_name.strip()
    if clean_table.startswith("odps."):
        return clean_table
    if "." in clean_table:
        project, clean_table = clean_table.split(".", 1)
    if not project:
        raise ValueError("mc_project is required to build table guid")
    return f"odps.{project}.{clean_table}"


def identify_layer(table_name: str) -> str:
    """Identify warehouse layer by table prefix."""
    base = table_name.split(".")[-1].lower()
    for prefix, layer in _LAYER_PREFIX_MAP.items():
        if base.startswith(prefix):
            return layer
    return "未分类"


_DMR_TEAM_PATTERN = re.compile(r"^dm[a-z]+_")


def identify_layer_ext(table_name: str) -> str:
    """Identify layer including DMR team-code tables."""
    base = table_name.split(".")[-1].lower()
    if base.startswith("dmr_"):
        return "DMR"
    layer = identify_layer(base)
    if layer != "未分类":
        return layer
    if _DMR_TEAM_PATTERN.match(base):
        return "DMR"
    return "未分类"


def parse_table_name(table_name: str) -> dict[str, str | None]:
    """Parse layer/domain/description/update mode from a warehouse table name."""
    base = table_name.split(".")[-1].lower()
    layer = identify_layer(base)
    match = re.match(r"^(ods|dwd|dim|dws)_([a-z0-9]+)_(.+)_([a-z0-9]+)$", base)
    if not match:
        return {
            "table_name": base,
            "layer": layer,
            "subject_domain": None,
            "description": None,
            "update_mode": None,
        }
    _, domain, description, update_mode = match.groups()
    return {
        "table_name": base,
        "layer": layer,
        "subject_domain": domain.upper(),
        "description": description,
        "update_mode": update_mode,
    }


def extract_node_id(task: dict[str, Any] | None) -> str | None:
    if not task:
        return None
    for key in ("taskId", "nodeId", "node_id", "id"):
        value = task.get(key)
        if value is not None:
            return str(value)
    return None


def extract_code_text(node_code: dict[str, Any] | None) -> str | None:
    if not node_code:
        return None
    for key in ("code", "codeText", "content", "nodeCode", "sql", "sqlText"):
        value = node_code.get(key)
        if value is not None:
            return str(value)
    return None


def normalize_table_name(value: str) -> str:
    clean = value.strip()
    if clean.startswith("odps."):
        parts = clean.split(".")
        return parts[-1].lower() if parts else clean.lower()
    return clean.split(".")[-1].lower()

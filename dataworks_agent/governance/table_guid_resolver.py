"""Resolve DataMap entity GUID for warehouse tables (BFF search + config default)."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.governance.table_name_parser import build_table_guid, normalize_table_name

logger = logging.getLogger(__name__)


async def resolve_table_guid(
    table_name: str,
    mc_project: str | None = None,
    *,
    bff: Any | None = None,
) -> tuple[str, str]:
    """Return ``(entity_guid, mc_project)`` for lineage / metadata calls."""
    base = normalize_table_name(table_name)
    if mc_project and mc_project.strip():
        project = mc_project.strip()
        return build_table_guid(base, project), project

    default_project = settings.dataworks_prod_schema

    if bff is not None:
        try:
            hits = await bff.search_tables(base, page_size=30)
        except Exception as exc:
            logger.debug("search_tables(%s) 失败: %s", base, exc)
            hits = []
        exact = [
            h for h in hits if isinstance(h, dict) and (h.get("table_name") or "").lower() == base
        ]
        if exact:
            preferred = default_project.lower()
            for hit in exact:
                project = (hit.get("project") or "").strip()
                if project.lower() == preferred:
                    guid = hit.get("entity_guid") or build_table_guid(base, project)
                    return str(guid), project
            hit = exact[0]
            project = (hit.get("project") or default_project).strip()
            guid = hit.get("entity_guid") or build_table_guid(base, project)
            return str(guid), project

    return build_table_guid(base, default_project), default_project

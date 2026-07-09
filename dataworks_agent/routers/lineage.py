"""血缘 API — 上游依赖 / 下游影响 / DAG 图。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from dataworks_agent.governance.lineage_store import LineageStore
from dataworks_agent.governance.table_guid_resolver import resolve_table_guid
from dataworks_agent.modeling.lineage_tracker import LineageTracker
from dataworks_agent.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)
tracker = LineageTracker()
store = LineageStore()


def _empty_lineage_hint() -> str:
    return (
        "未查到血缘数据。请确认表名正确；MC 项目留空时会自动搜索（优先 prod schema）；"
        "若仍为空，请检查 Cookie / MCP 是否有效。"
    )


@router.get("/upstream/{table_name}")
async def get_upstream(
    table_name: str,
    mc_project: str = Query(default="", description="MC 项目名，留空则自动解析"),
    refresh: bool = Query(default=False, description="强制实时重算,忽略缓存"),
):
    """查询上游依赖 — 优先读 lineage_edges 持久化缓存。"""
    if not refresh and store.is_fresh(table_name):
        cached = store.get_upstream(table_name)
        if cached:
            return {
                "table": table_name,
                "upstream": [{"upstream_table": r["source_table"]} for r in cached],
                "cached": True,
                "cached_at": cached[0]["cached_at"],
            }

    bff = app_state._bff_client
    upstream: list[dict] = []
    seen: set[str] = set()
    guid = ""
    resolved_project = mc_project or None

    if bff is not None:
        try:
            guid, resolved_project = await resolve_table_guid(
                table_name, mc_project or None, bff=bff
            )
            data = await bff.list_lineage(guid)
            if data:
                up_data = data.get("up", {})
                if isinstance(up_data, dict):
                    entity_list = up_data.get("entityList", [])
                    for entity in entity_list:
                        if not isinstance(entity, dict):
                            continue
                        table_guid = entity.get("entityGuid", "")
                        table_name_found = entity.get("tableName", "")
                        if table_guid and table_guid not in seen:
                            seen.add(table_guid)
                            upstream.append(
                                {
                                    "upstream_table": table_name_found
                                    or str(table_guid).split(".")[-1],
                                    "guid": table_guid,
                                    "relationship": entity.get("relationshipType", ""),
                                }
                            )
        except Exception as e:
            logger.warning("BFF listLineage 失败: %s", e)

    if not upstream:
        nodes = await tracker.trace_upstream(table_name, mc_project or None)
        upstream = [n.model_dump() for n in nodes]
        for n in nodes:
            store.save_edges(
                source_table=n.upstream_table,
                target_table=table_name,
                task_id=n.task_id,
                task_name=n.task_name,
            )

    if not guid and bff is not None:
        try:
            guid, resolved_project = await resolve_table_guid(
                table_name, mc_project or None, bff=bff
            )
        except Exception:
            pass

    payload: dict = {
        "table": table_name,
        "guid": guid,
        "mc_project": resolved_project,
        "upstream": upstream,
        "total": len(upstream),
        "cached": False,
    }
    if not upstream:
        payload["note"] = _empty_lineage_hint()
    return payload


@router.get("/downstream/{table_name}")
async def get_downstream(
    table_name: str,
    mc_project: str = Query(default="", description="MC 项目名，留空则自动解析"),
    depth: int = Query(default=3, ge=1, le=10),
):
    """查询下游影响 — 基于 BFF dma/listLineage 全量 DAG,反向过滤。"""
    bff = app_state._bff_client
    if bff is None:
        raise HTTPException(
            status_code=503, detail="BFF client not available (Cookie channel not initialized)"
        )
    try:
        guid, resolved_project = await resolve_table_guid(table_name, mc_project or None, bff=bff)
        data = await bff.list_lineage(guid)
    except Exception as exc:
        logger.warning("listLineage 失败 (table=%s): %s", table_name, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"调用 listLineage 失败: {exc}") from exc

    if not data:
        return {
            "table": table_name,
            "guid": guid,
            "mc_project": resolved_project,
            "downstream": [],
            "note": "DataWorks 未返回血缘数据",
        }

    downstream: list[dict] = []
    seen: set[str] = set()

    down_data = data.get("down", {})
    if isinstance(down_data, dict):
        entity_list = down_data.get("entityList", [])
        for entity in entity_list:
            if not isinstance(entity, dict):
                continue
            table_guid = entity.get("entityGuid", "")
            table_name_found = entity.get("tableName", "")
            if table_guid and table_guid not in seen:
                seen.add(table_guid)
                downstream.append(
                    {
                        "table": table_name_found or str(table_guid).split(".")[-1],
                        "guid": table_guid,
                    }
                )
            if len(downstream) >= 200:
                break

    payload: dict = {
        "table": table_name,
        "guid": guid,
        "mc_project": resolved_project,
        "depth": depth,
        "downstream": downstream,
        "total": len(downstream),
    }
    if not downstream:
        payload["note"] = _empty_lineage_hint()
    return payload


@router.get("/graph/{table_name}")
async def get_graph(
    table_name: str,
    max_depth: int = 3,
    mc_project: str = Query(default="", description="MC 项目名，留空则自动解析"),
):
    """获取血缘 DAG 图。"""
    graph = await tracker.build_lineage_graph(
        table_name, max_depth=max_depth, mc_project=mc_project or None
    )
    payload = graph.model_dump()
    if not payload.get("nodes") and not payload.get("edges"):
        payload["note"] = _empty_lineage_hint()
    return payload

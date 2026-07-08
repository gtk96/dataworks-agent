"""血缘 API — 上游依赖 / 下游影响 / DAG 图。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from dataworks_agent.governance.lineage_store import LineageStore
from dataworks_agent.governance.table_name_parser import build_table_guid
from dataworks_agent.modeling.lineage_tracker import LineageTracker
from dataworks_agent.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)
tracker = LineageTracker()
store = LineageStore()


@router.get("/upstream/{table_name}")
async def get_upstream(
    table_name: str, refresh: bool = Query(default=False, description="强制实时重算,忽略缓存")
):
    """查询上游依赖 — 优先读 lineage_edges 持久化缓存。

    DataWorks BFF listLineage 返回格式:
    {"up": {"entityList": [...]}, "down": {"entityList": [...]}}
    其中 up.entityList 包含上游表信息。
    """
    if not refresh and store.is_fresh(table_name):
        cached = store.get_upstream(table_name)
        if cached:
            return {
                "table": table_name,
                "upstream": [{"upstream_table": r["source_table"]} for r in cached],
                "cached": True,
                "cached_at": cached[0]["cached_at"],
            }

    guid = build_table_guid(table_name)
    bff = app_state._bff_client
    upstream: list[dict] = []
    seen: set[str] = set()

    # 尝试使用 BFF 获取上游表
    if bff is not None:
        try:
            data = await bff.list_lineage(guid)
            if data:
                # 提取 up.entityList（上游表）
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

    # 如果 BFF 没有返回数据，使用 MCP
    if not upstream:
        nodes = await tracker.trace_upstream(table_name)
        upstream = [n.model_dump() for n in nodes]
        # 写回缓存
        for n in nodes:
            store.save_edges(
                source_table=n.upstream_table,
                target_table=table_name,
                task_id=n.task_id,
                task_name=n.task_name,
            )

    return {
        "table": table_name,
        "guid": guid,
        "upstream": upstream,
        "total": len(upstream),
        "cached": False,
    }


@router.get("/downstream/{table_name}")
async def get_downstream(
    table_name: str,
    mc_project: str = Query(default="", description="MC 项目名,默认 prod schema"),
    depth: int = Query(default=3, ge=1, le=10),
):
    """查询下游影响 — 基于 BFF dma/listLineage 全量 DAG,反向过滤。

    DataWorks BFF listLineage 返回格式:
    {"up": {"entityList": [...]}, "down": {"entityList": [...]}}
    其中 entityList 包含实体信息,tableName 字段表示表名。
    """
    guid = build_table_guid(table_name, mc_project or None)
    bff = app_state._bff_client
    if bff is None:
        raise HTTPException(
            status_code=503, detail="BFF client not available (Cookie channel not initialized)"
        )
    try:
        data = await bff.list_lineage(guid)
    except Exception as exc:
        logger.warning("listLineage 失败 (guid=%s): %s", guid, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"调用 listLineage 失败: {exc}") from exc

    if not data:
        return {
            "table": table_name,
            "guid": guid,
            "downstream": [],
            "note": "DataWorks 未返回血缘数据",
        }

    # BFF 返回格式: {"up": {"entityList": [...]}, "down": {"entityList": [...]}}
    # up 是上游表, down 是下游表（引用当前表的表）
    downstream: list[dict] = []
    seen: set[str] = set()

    # 提取 down.entityList（下游表）
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

    return {
        "table": table_name,
        "guid": guid,
        "depth": depth,
        "downstream": downstream,
        "total": len(downstream),
    }


@router.get("/graph/{table_name}")
async def get_graph(table_name: str, max_depth: int = 3):
    """获取血缘 DAG 图。"""
    graph = await tracker.build_lineage_graph(table_name, max_depth=max_depth)
    return graph.model_dump()

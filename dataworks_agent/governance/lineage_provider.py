"""OpenAPI 血缘适配器（Task 8c）。

把 `lineage_service` 依赖的 4 个 BFF 方法映射到 DataWorks OpenAPI 2024-05-18，
返回 `extract_node_id` / `extract_parent_table_name` / `extract_code_text` 认识的
dict 形状，使 BFS 遍历与导出逻辑无需改动。

真机响应结构见 CLAUDE.md §7：
- list_node_dependencies → PagingInfo.Nodes[]（父节点，含 Id/Name/Outputs）；
- get_node → Node.Spec（FlowSpec JSON 字符串，脚本在 spec.nodes[0].script.content）；
- list_nodes → PagingInfo.Nodes[]（Name≈表名，Outputs.NodeOutputs[].Data=dataworks.<表>）。

注：DataMap 表/列血缘（list_lineages）需 RAM `dataworks:ListLineages`，未授权时
本适配器不依赖它；节点级依赖足以支撑现有 lineage_service 的 BFS。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient

logger = logging.getLogger(__name__)


def get_lineage_provider(*, mc_project: str | None = None) -> Any:
    """选择血缘后端：BFF（Cookie，低延迟）优先，OpenAPI（AK/SK）兜底。"""
    from fastapi import HTTPException

    from dataworks_agent.config import settings
    from dataworks_agent.state import app_state

    bff = getattr(app_state, "_bff_client", None)
    if bff is not None:
        return bff

    client = getattr(app_state, "_openapi_client", None)
    if client is not None:
        return OpenAPILineageProvider(client, mc_project=mc_project or settings.maxcompute_project)

    raise HTTPException(
        status_code=503,
        detail="血缘服务不可用：请配置 DataWorks Cookie 或 AK/SK",
    )


def _to_map(body: Any) -> dict[str, Any]:
    """SDK 响应对象 → dict（PascalCase 键，同真机 JSON）。"""
    if body is None:
        return {}
    if hasattr(body, "to_map"):
        return body.to_map() or {}
    if isinstance(body, dict):
        return body
    return {}


def _nodes_of(body: Any) -> list[dict[str, Any]]:
    data = _to_map(body)
    paging = data.get("PagingInfo") or {}
    return paging.get("Nodes") or []


def _script_content_from_spec(spec_str: str | None) -> str | None:
    """从节点 FlowSpec JSON 中取脚本正文 spec.nodes[0].script.content。"""
    if not spec_str:
        return None
    try:
        spec = json.loads(spec_str)
    except (json.JSONDecodeError, TypeError):
        return None
    nodes = (spec.get("spec") or {}).get("nodes") or []
    for node in nodes:
        content = (node.get("script") or {}).get("content")
        if content:
            return content
    return None


class OpenAPILineageProvider:
    """以 DataWorks OpenAPI 支撑 lineage_service 的血缘读取。"""

    def __init__(
        self,
        client: DataWorksOpenAPIClient,
        *,
        mc_project: str,
        page_size: int = 100,
        max_pages: int = 50,
        nodes_cache_ttl: int = 300,
    ) -> None:
        self._client = client
        self._mc_project = mc_project
        self._page_size = page_size
        self._max_pages = max_pages
        self._nodes_cache_ttl = nodes_cache_ttl
        self._nodes_cache: list[dict[str, Any]] | None = None
        self._nodes_cache_at: float = 0.0

    async def _iter_all_nodes(self) -> list[dict[str, Any]]:
        """分页拉取项目下节点（ListNodes 无按名过滤，只能客户端匹配）。"""
        if (
            self._nodes_cache is not None
            and (time.time() - self._nodes_cache_at) < self._nodes_cache_ttl
        ):
            return self._nodes_cache

        collected: list[dict[str, Any]] = []
        for page in range(1, self._max_pages + 1):
            body = await self._client.list_nodes(page_number=page, page_size=self._page_size)
            batch = _nodes_of(body)
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < self._page_size:
                break
        self._nodes_cache = collected
        self._nodes_cache_at = time.time()
        return collected

    @staticmethod
    def _node_outputs_tables(node: dict[str, Any]) -> set[str]:
        outs = (node.get("Outputs") or {}).get("NodeOutputs") or []
        tables: set[str] = set()
        for o in outs:
            data = o.get("Data")
            if data:
                tables.add(str(data).split(".")[-1].lower())
        return tables

    async def get_upstream_tasks(self, table_guid: str) -> list[dict[str, Any]]:
        """按产出表定位产出节点（替代 BFF get_upstream_tasks）。

        table_guid 形如 odps.<project>.<table>；匹配 Name==表 或 Outputs 含该表。
        """
        table = table_guid.split(".")[-1].lower()
        for node in await self._iter_all_nodes():
            name = str(node.get("Name") or "").lower()
            if name == table or table in self._node_outputs_tables(node):
                return [{"id": node.get("Id"), "name": node.get("Name")}]
        return []

    async def get_node_list(
        self, *, search: str, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """按名称子串在项目节点中过滤（替代 BFF get_node_list 搜索）。"""
        key = search.lower()
        results: list[dict[str, Any]] = []
        for node in await self._iter_all_nodes():
            name = str(node.get("Name") or "").lower()
            if key in name:
                results.append({"id": node.get("Id"), "name": node.get("Name")})
        return results

    async def get_node_parents_by_depth(
        self, *, node_id: int | str, env: str = "prod"
    ) -> list[dict[str, Any]] | None:
        """取节点上游父依赖（替代 BFF get_node_parents_by_depth）。

        list_node_dependencies 返回集合含节点自身；调用方 BFS 会跳过 self。
        """
        try:
            body = await self._client.list_node_dependencies(str(node_id))
        except Exception as exc:
            logger.debug("list_node_dependencies(%s) 失败: %s", node_id, exc)
            return None
        return [{"id": n.get("Id"), "name": n.get("Name")} for n in _nodes_of(body)]

    async def get_node_code(
        self, node_id: int | str, *, env: str = "prod"
    ) -> dict[str, Any] | None:
        """取节点脚本正文（替代 BFF get_node_code）。"""
        body = await self._client.get_node(str(node_id))
        data = _to_map(body)
        spec_str = (data.get("Node") or {}).get("Spec")
        content = _script_content_from_spec(spec_str)
        return {"content": content} if content is not None else {}

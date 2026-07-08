"""只读探针 — 连真机 DataWorks OpenAPI 2024-05-18，打印真实响应结构。

用途：为 Task 8c/8b 的调用点改写取真实响应形状（血缘/节点/元数据/数据源），
只调用只读接口，绝不做任何写/删操作，不回显 AK/SK。

用法：
  # 先在 .env 配好 ALIYUN_ACCESS_KEY_ID / SECRET
  uv run python -m dataworks_agent.scripts.probe_openapi --tables dwd_mkt
  uv run python -m dataworks_agent.scripts.probe_openapi --lineage dataworks.dwd_mkt_ad_group_day
  uv run python -m dataworks_agent.scripts.probe_openapi --nodes
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient, OpenAPIError
from dataworks_agent.auth import CredentialMissingError, load_credentials
from dataworks_agent.config import settings


def _dump(label: str, body: Any, *, max_len: int = 4000) -> None:
    """打印响应结构（TeaModel → dict），截断超长值。"""
    print(f"\n===== {label} =====")
    try:
        data = body.to_map() if hasattr(body, "to_map") else body
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        text = f"<无法序列化: {e}> repr={body!r}"
    if len(text) > max_len:
        text = text[:max_len] + f"\n... [truncated, total {len(text)} chars]"
    print(text)


async def main() -> None:
    parser = argparse.ArgumentParser(description="DataWorks OpenAPI 只读探针")
    parser.add_argument("--tables", metavar="NAME", help="按名称搜索元数据表 (list_tables)")
    parser.add_argument("--table-id", metavar="ID", help="按实体 id 取表详情 (get_table)")
    parser.add_argument(
        "--lineage", metavar="ENTITY", help="按实体名查上游血缘 (list_lineages dst=)"
    )
    parser.add_argument("--nodes", action="store_true", help="列出节点 (list_nodes)")
    parser.add_argument(
        "--node-id", metavar="ID", help="取节点详情 (get_node) + 依赖 (list_node_dependencies)"
    )
    parser.add_argument(
        "--provider-node", metavar="ID", help="用 OpenAPILineageProvider 取父依赖+脚本(真机验证 8c)"
    )
    args = parser.parse_args()

    try:
        creds = load_credentials()
    except CredentialMissingError as e:
        print(f"[凭证缺失] {e}")
        return

    client = DataWorksOpenAPIClient(
        creds=creds,
        region=settings.dataworks_region,
        endpoint=f"dataworks.{settings.dataworks_region}.aliyuncs.com",
        project_id=settings.dataworks_project_id,
    )

    async def _safe(label: str, coro):
        try:
            _dump(label, await coro)
        except OpenAPIError as e:
            print(f"\n===== {label} =====\n[OpenAPIError] code={e.code} message={e.message}")
        except Exception as e:
            print(f"\n===== {label} =====\n[异常] {type(e).__name__}: {e}")

    if args.tables:
        await _safe(
            f"list_tables(name={args.tables})", client.list_tables(name=args.tables, page_size=10)
        )
    if args.table_id:
        await _safe(
            f"get_table(id={args.table_id})",
            client.get_table(args.table_id, include_business_metadata=True),
        )
    if args.lineage:
        await _safe(
            f"list_lineages(dst_entity_name={args.lineage})",
            client.list_lineages(
                dst_entity_name=args.lineage, need_attach_relationship=True, page_size=10
            ),
        )
    if args.nodes:
        await _safe("list_nodes(page_size=10)", client.list_nodes(page_size=10))
    if args.node_id:
        await _safe(f"get_node(id={args.node_id})", client.get_node(args.node_id))
        await _safe(
            f"list_node_dependencies(id={args.node_id})",
            client.list_node_dependencies(args.node_id, page_size=10),
        )

    if args.provider_node:
        from dataworks_agent.governance.lineage_provider import OpenAPILineageProvider

        provider = OpenAPILineageProvider(client, mc_project=settings.maxcompute_project)

        async def _probe_provider(nid: str):
            parents = await provider.get_node_parents_by_depth(node_id=nid)
            print(f"\n===== provider.get_node_parents_by_depth({nid}) =====")
            print(json.dumps(parents, ensure_ascii=False, indent=2, default=str))
            code = await provider.get_node_code(nid)
            content = (code or {}).get("content") or ""
            print(f"\n===== provider.get_node_code({nid}) — content 前 300 字 =====")
            print(content[:300] if content else "<空>")

        await _safe(f"provider(node={args.provider_node})", _probe_provider(args.provider_node))

    if not any(
        [args.tables, args.table_id, args.lineage, args.nodes, args.node_id, args.provider_node]
    ):
        print(
            "未指定探针目标，请加参数，如 --tables dwd_mkt / --nodes / --lineage dataworks.<表名>"
        )


if __name__ == "__main__":
    asyncio.run(main())

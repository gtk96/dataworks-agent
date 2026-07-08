"""Lineage export pure helpers — preview, prune, archive."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.governance.lineage_models import (
    CollectedNode,
    DependencyEdge,
    ExportMeta,
    LineageNode,
    RootNode,
    TraversalResult,
)
from dataworks_agent.governance.table_name_parser import identify_layer_ext

MAX_NODES = 500
MAX_DEPTH = 50

_EXPORT_DIR = Path(settings.archive_dir) / "lineage_export"
_LAYER_TO_DIR = {
    "ODS": "ods/",
    "DWD": "dwd/",
    "DWS": "dws/",
    "DIM": "dim/",
    "DMR": "dmr/",
}
_UNCLASSIFIED_DIR = "_unclassified/"


def extract_parent_table_name(parent_record: dict[str, Any]) -> str | None:
    candidate: Any = None
    for key in ("name", "nodeName", "outputTableName", "tableName", "entityName"):
        val = parent_record.get(key)
        if val is not None and str(val).strip():
            candidate = str(val).strip()
            break
    if candidate is None:
        return None
    return candidate.split(".")[-1].lower()


def build_preview(root: RootNode, result: TraversalResult) -> dict[str, Any]:
    return {
        "root_table": root.table_name,
        "root_node_id": root.node_id,
        "nodes": [
            {
                "node_id": node.node_id,
                "table_name": node.table_name,
                "layer": node.layer,
                "depth": node.depth,
                "is_truncation_point": node.is_truncation_point,
            }
            for node in result.nodes.values()
        ],
        "dependencies": [
            {
                "parent_node_id": edge.parent_node_id,
                "child_node_id": edge.child_node_id,
            }
            for edge in result.edges
        ],
        "summary": {
            "node_total": len(result.nodes),
            "truncation_count": sum(1 for n in result.nodes.values() if n.is_truncation_point),
            "reached_limit": result.reached_limit,
        },
    }


def prune_excluded(
    result: TraversalResult,
    root_id: str,
    excluded_node_ids: set[str],
) -> TraversalResult:
    if not excluded_node_ids:
        return result

    child_to_parents: dict[str, list[str]] = {}
    for edge in result.edges:
        child_to_parents.setdefault(edge.child_node_id, []).append(edge.parent_node_id)

    reachable: set[str] = set()
    queue = [root_id]
    reachable.add(root_id)
    idx = 0
    while idx < len(queue):
        current = queue[idx]
        idx += 1
        for parent_id in child_to_parents.get(current, []):
            if parent_id not in excluded_node_ids and parent_id not in reachable:
                reachable.add(parent_id)
                queue.append(parent_id)

    kept_node_ids = {
        nid for nid in result.nodes if nid in reachable and nid not in excluded_node_ids
    }
    kept_edges = [
        edge
        for edge in result.edges
        if edge.parent_node_id in kept_node_ids and edge.child_node_id in kept_node_ids
    ]

    before_parents: dict[str, set[str]] = {}
    for edge in result.edges:
        if edge.child_node_id in kept_node_ids:
            before_parents.setdefault(edge.child_node_id, set()).add(edge.parent_node_id)
    after_parents: dict[str, set[str]] = {}
    for edge in kept_edges:
        after_parents.setdefault(edge.child_node_id, set()).add(edge.parent_node_id)

    new_nodes: dict[str, LineageNode] = {}
    for nid in kept_node_ids:
        original = result.nodes[nid]
        had_parents = bool(before_parents.get(nid))
        fewer_parents = before_parents.get(nid, set()) != after_parents.get(nid, set())
        if original.is_truncation_point or (had_parents and fewer_parents):
            new_nodes[nid] = LineageNode(
                node_id=original.node_id,
                table_name=original.table_name,
                layer=original.layer,
                project_id=original.project_id,
                depth=original.depth,
                status=original.status,
                error=original.error,
                is_truncation_point=True,
            )
        else:
            new_nodes[nid] = original

    return TraversalResult(nodes=new_nodes, edges=kept_edges, reached_limit=result.reached_limit)


def build_archive(
    nodes: list[CollectedNode],
    edges: list[DependencyEdge],
    meta: ExportMeta,
) -> Path:
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    zip_path = _EXPORT_DIR / f"{meta.root_table}_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for collected in nodes:
            node = collected.node
            layer_dir = _LAYER_TO_DIR.get(node.layer, _UNCLASSIFIED_DIR)
            table_part = (node.table_name or "unknown").rstrip("_") or "unknown"
            sql_filename = f"{layer_dir}{table_part}__{node.node_id}.sql"

            if collected.code_text and collected.code_text.strip():
                content = collected.code_text
            elif node.status == "error":
                content = f"-- 代码获取失败: {node.error or '未知错误'}"
            else:
                content = "-- 代码缺失，获取返回空"
            zf.writestr(sql_filename, content)

        manifest = {
            "meta": {
                "root_table": meta.root_table,
                "root_node_id": meta.root_node_id,
                "generated_at": meta.generated_at,
                "node_total": meta.node_total,
                "truncation_count": meta.truncation_count,
                "reached_limit": meta.reached_limit,
            },
            "nodes": [
                {
                    "node_id": collected.node.node_id,
                    "table_name": collected.node.table_name,
                    "layer": collected.node.layer,
                    "project_id": collected.node.project_id,
                    "status": collected.node.status,
                    "is_truncation_point": collected.node.is_truncation_point,
                }
                for collected in nodes
            ],
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        dependencies = [
            {
                "parent_node_id": edge.parent_node_id,
                "child_node_id": edge.child_node_id,
            }
            for edge in edges
        ]
        zf.writestr("dependencies.json", json.dumps(dependencies, ensure_ascii=False, indent=2))

    return zip_path


def make_root_node(node_id: str, table_name: str) -> RootNode:
    return RootNode(node_id=node_id, table_name=table_name)


def make_lineage_node(node_id: str, table_name: str | None, depth: int) -> LineageNode:
    return LineageNode(
        node_id=node_id,
        table_name=table_name,
        layer=identify_layer_ext(table_name or ""),
        depth=depth,
    )

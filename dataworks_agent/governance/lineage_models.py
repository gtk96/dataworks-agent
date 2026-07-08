"""Internal dataclasses for lineage code export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


@dataclass
class LineageNode:
    node_id: str
    table_name: str | None = None
    layer: str = "未分类"
    project_id: str | None = None
    depth: int = 0
    status: str = "ok"
    error: str | None = None
    is_truncation_point: bool = False


@dataclass(frozen=True)
class DependencyEdge:
    parent_node_id: str
    child_node_id: str


@dataclass(frozen=True)
class CollectedNode:
    node: LineageNode
    code_text: str | None


@dataclass(frozen=True)
class ExportMeta:
    root_table: str
    root_node_id: str
    generated_at: str
    node_total: int
    truncation_count: int
    reached_limit: bool


class RootNode(NamedTuple):
    node_id: str
    table_name: str


class TraversalResult(NamedTuple):
    nodes: dict[str, LineageNode]
    edges: list[DependencyEdge]
    reached_limit: bool

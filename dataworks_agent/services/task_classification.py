"""Task node-type inference and dashboard aggregation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, literal_column, or_

from dataworks_agent.db.models import ModelingTaskModel

NODE_TYPE_HOLO = "holo"
NODE_TYPE_DI = "di"
NODE_TYPE_ODPS = "odps-sql"

NODE_TYPE_LABELS: dict[str, str] = {
    NODE_TYPE_HOLO: "Holo SQL",
    NODE_TYPE_DI: "数据集成 DI",
    NODE_TYPE_ODPS: "MaxCompute SQL",
}

_PIPELINE_TYPE_MAP = {
    "ods_oss": NODE_TYPE_ODPS,
    "ods_realtime": NODE_TYPE_DI,
}


def infer_node_type(task: ModelingTaskModel) -> str:
    """Infer node type for legacy rows missing node_type."""
    explicit = (task.node_type or "").strip().lower()
    if explicit in NODE_TYPE_LABELS:
        return explicit

    task_id = task.task_id or ""
    if task_id.startswith("holo_"):
        return NODE_TYPE_HOLO
    if task_id.startswith("di_"):
        return NODE_TYPE_DI

    if task_id.startswith("imp_") or task_id.startswith("task_"):
        return NODE_TYPE_ODPS

    layer = (task.target_layer or "").upper()
    if layer in {"DWD", "DWS", "DMR", "DIM"}:
        return NODE_TYPE_ODPS

    return NODE_TYPE_ODPS


def pipeline_node_type(pipeline_type: str) -> str:
    return _PIPELINE_TYPE_MAP.get(pipeline_type, NODE_TYPE_ODPS)


def infer_node_type_sql():
    """把 infer_node_type 规则编译成 SQL CASE WHEN 表达式（v15 F2-5）。

    与 infer_node_type 行为等价（基于同一规则集），可在 WHERE/HAVING
    里直接做 node_type 过滤，避免全表拉到 Python 内存后再 filter。
    优先级：
      1) 显式 node_type 命中已知标签 → 用它
      2) task_id 前缀 holo_/di_/imp_/task_ → 对应类型
      3) target_layer 命中 DWD/DWS/DMR/DIM → odps-sql
      4) 兜底 → odps-sql
    """
    explicit = ModelingTaskModel.node_type
    lower_explicit = func.lower(func.trim(explicit))
    case1 = case(
        (lower_explicit.in_([NODE_TYPE_HOLO, NODE_TYPE_DI, NODE_TYPE_ODPS]), lower_explicit),
        else_=None,
    )
    tid = ModelingTaskModel.task_id
    case2 = case(
        (tid.like("holo_%"), literal_column(f"'{NODE_TYPE_HOLO}'")),
        (tid.like("di_%"), literal_column(f"'{NODE_TYPE_DI}'")),
        (or_(tid.like("imp_%"), tid.like("task_%")), literal_column(f"'{NODE_TYPE_ODPS}'")),
        else_=None,
    )
    layer = func.upper(ModelingTaskModel.target_layer)
    case3 = case(
        (layer.in_(["DWD", "DWS", "DMR", "DIM"]), literal_column(f"'{NODE_TYPE_ODPS}'")),
        else_=None,
    )
    return func.coalesce(case1, case2, case3, literal_column(f"'{NODE_TYPE_ODPS}'"))


def _empty_bucket() -> dict[str, int]:
    return {"total": 0, "completed": 0, "failed": 0, "running": 0, "pending": 0}


def _classify_status(status: str) -> str:
    """把状态字符串归到 running/completed/failed/pending 四桶之一（其他返回 None）。"""
    normalized = (status or "").lower()
    if normalized in {"completed", "success"}:
        return "completed"
    if normalized in {"failed", "partial"}:
        return "failed"
    if normalized in {"pending", "queued"}:
        return "pending"
    if normalized in {
        "running",
        "ddl_gen",
        "table_cre",
        "root_check",
        "dml_write",
        "sched_cfg",
        "testing",
        "claimed",
    }:
        return "running"
    return None


def _bump(bucket: dict[str, int], status: str) -> None:
    bucket["total"] += 1
    cls = _classify_status(status)
    if cls:
        bucket[cls] += 1


def aggregate_type_breakdown(db: Any) -> dict[str, dict[str, int]]:
    """Aggregate modeling_tasks by node type (includes workspace/pipeline records).

    优先走 SQL GROUP BY 避免全表扫描到 Python 内存；null node_type 的行
    回退到 infer_node_type 推断。
    """
    from sqlalchemy import func, select

    buckets = {key: _empty_bucket() for key in NODE_TYPE_LABELS}

    # 1) 已标记 node_type 的行走 SQL GROUP BY（快速路径）
    stmt = (
        select(
            ModelingTaskModel.node_type,
            ModelingTaskModel.status,
            func.count().label("cnt"),
        )
        .where(ModelingTaskModel.node_type.isnot(None))
        .where(ModelingTaskModel.node_type != "")
        .group_by(ModelingTaskModel.node_type, ModelingTaskModel.status)
    )
    rows = db.execute(stmt).all()
    for r in rows:
        ntype = (r.node_type or "").strip().lower()
        if ntype not in NODE_TYPE_LABELS:
            continue
        bucket = buckets[ntype]
        bucket["total"] += r.cnt
        cls = _classify_status(r.status)
        if cls:
            bucket[cls] += r.cnt

    # 2) node_type 为 null/空的行走 SQL 推断聚合（避免全表拉到 Python 内存）
    #    复用 v15 的 infer_node_type_sql()，与 Python 版 infer_node_type 规则等价，
    #    把推断逻辑下推到数据库一次 GROUP BY，消除 legacy 行的 O(N) 内存循环。
    #    （这是 F2-5 在 dashboard 聚合侧的最后残留——G1 优化）
    inferred_type = infer_node_type_sql()
    legacy_stmt = (
        select(
            inferred_type.label("ntype"),
            ModelingTaskModel.status,
            func.count().label("cnt"),
        )
        .where((ModelingTaskModel.node_type.is_(None)) | (ModelingTaskModel.node_type == ""))
        .group_by(inferred_type, ModelingTaskModel.status)
    )
    for r in db.execute(legacy_stmt).all():
        ntype = (r.ntype or "").strip().lower()
        if ntype not in NODE_TYPE_LABELS:
            continue
        bucket = buckets[ntype]
        bucket["total"] += r.cnt
        cls = _classify_status(r.status)
        if cls:
            bucket[cls] += r.cnt

    return buckets

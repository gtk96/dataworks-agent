"""LineageStore — lineage_edges 表的持久化缓存。

血缘实时计算慢(每次都要走 BFF/MCP),把最近一次解析的上下游边落表,
下次同表查询直接读缓存,缓存缺失或过期时回退实时计算并写回。

数据模型 (db.models.LineageEdgeModel):
- source_table: 上游表名 (无 schema 前缀)
- target_table: 下游表名 (无 schema 前缀)
- task_id / task_name: 触发此边的 DataWorks 节点 (可空)
- cached_at: ISO 时间戳,用于 TTL 判断
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import LineageEdgeModel

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(hours=24)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _strip_schema(table: str) -> str:
    """去掉 odps.<project>.<table> 的 schema 前缀,只留表名。"""
    if not table:
        return table
    parts = table.split(".")
    return parts[-1] if len(parts) > 1 else table


class LineageStore:
    """lineage_edges 表的 CRUD 封装。"""

    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self.ttl = ttl

    def save_edges(
        self,
        source_table: str,
        target_table: str,
        task_id: str = "",
        task_name: str = "",
    ) -> None:
        """写入一条边(source -> target 表示 source 被 target 消费)。

        同 (source, target) 已有记录时只更新 cached_at + task_id/name,避免重复。
        """
        src = _strip_schema(source_table)
        tgt = _strip_schema(target_table)
        if not src or not tgt or src == tgt:
            return
        with SessionLocal() as db:
            existing = db.execute(
                select(LineageEdgeModel).where(
                    LineageEdgeModel.source_table == src,
                    LineageEdgeModel.target_table == tgt,
                )
            ).scalar_one_or_none()
            now = _utc_now()
            if existing:
                existing.cached_at = now
                if task_id:
                    existing.task_id = task_id
                if task_name:
                    existing.task_name = task_name
            else:
                db.add(
                    LineageEdgeModel(
                        source_table=src,
                        target_table=tgt,
                        task_id=task_id,
                        task_name=task_name,
                        cached_at=now,
                    )
                )
            db.commit()

    def save_edges_batch(self, edges: Iterable[dict[str, str]]) -> int:
        """批量写入,返回实际写入条数。"""
        count = 0
        for e in edges:
            self.save_edges(
                source_table=e.get("source_table", ""),
                target_table=e.get("target_table", ""),
                task_id=e.get("task_id", ""),
                task_name=e.get("task_name", ""),
            )
            count += 1
        return count

    def get_upstream(self, table: str) -> list[dict[str, str]]:
        """返回 table 的上游表列表 [{table, task_id, task_name, cached_at}, ...]。"""
        tgt = _strip_schema(table)
        with SessionLocal() as db:
            stmt = select(LineageEdgeModel).where(LineageEdgeModel.target_table == tgt)
            rows = db.execute(stmt).scalars().all()
            return [self._row_to_dict(r) for r in self._filter_fresh(rows)]

    def get_downstream(self, table: str) -> list[dict[str, str]]:
        """返回 table 的下游表列表。"""
        src = _strip_schema(table)
        with SessionLocal() as db:
            stmt = select(LineageEdgeModel).where(LineageEdgeModel.source_table == src)
            rows = db.execute(stmt).scalars().all()
            return [self._row_to_dict(r) for r in self._filter_fresh(rows)]

    def is_fresh(self, table: str) -> bool:
        """table 是否有未过期的缓存(任一边存在且最新 cached_at < TTL)。"""
        with SessionLocal() as db:
            stmt = (
                select(LineageEdgeModel.cached_at)
                .where(
                    (LineageEdgeModel.source_table == _strip_schema(table))
                    | (LineageEdgeModel.target_table == _strip_schema(table))
                )
                .order_by(LineageEdgeModel.cached_at.desc())
                .limit(1)
            )
            row = db.execute(stmt).scalar_one_or_none()
            if not row:
                return False
            try:
                cached_at = datetime.fromisoformat(row)
            except ValueError:
                return False
            return datetime.now(UTC) - cached_at < self.ttl

    def clear(self, table: str) -> int:
        """删除与 table 相关的所有边,返回删除条数。"""
        tgt = _strip_schema(table)
        with SessionLocal() as db:
            stmt = delete(LineageEdgeModel).where(
                (LineageEdgeModel.source_table == tgt) | (LineageEdgeModel.target_table == tgt)
            )
            result = db.execute(stmt)
            db.commit()
            return result.rowcount or 0

    def _filter_fresh(self, rows: list[LineageEdgeModel]) -> list[LineageEdgeModel]:
        now = datetime.now(UTC)
        fresh: list[LineageEdgeModel] = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r.cached_at)
            except ValueError:
                continue
            if now - ts < self.ttl:
                fresh.append(r)
        return fresh

    @staticmethod
    def _row_to_dict(r: LineageEdgeModel) -> dict[str, str]:
        return {
            "source_table": r.source_table,
            "target_table": r.target_table,
            "task_id": r.task_id,
            "task_name": r.task_name,
            "cached_at": r.cached_at,
        }

"""BusMatrixManager — 总线矩阵管理，维度建模核心工具。"""

from __future__ import annotations

import json
import logging

from dataworks_agent.schemas import BusMatrixEntry

logger = logging.getLogger(__name__)


class BusMatrixManager:
    """总线矩阵 — 业务过程 × 维度关联管理。"""

    async def get_matrix(self) -> list[BusMatrixEntry]:
        """从 SQLite 读取已登记的矩阵。"""
        from sqlalchemy import select

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import BusMatrixCellModel

        with SessionLocal() as db:
            stmt = select(BusMatrixCellModel)
            rows = db.execute(stmt).scalars().all()
            return [
                BusMatrixEntry(
                    domain=r.domain,
                    dimension=r.dimension,
                    has_link=bool(r.has_link),
                    tables=json.loads(r.tables_json) if r.tables_json else [],
                )
                for r in rows
            ]

    async def register_link(
        self, domain: str, dimension: str, tables: list[str] | None = None
    ) -> None:
        """登记一个业务域×维度的关联。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import BusMatrixCellModel

        with SessionLocal() as db:
            cell = BusMatrixCellModel(
                domain=domain,
                dimension=dimension,
                has_link=1,
                tables_json=json.dumps(tables or [], ensure_ascii=False),
            )
            db.add(cell)
            db.commit()

    async def check_consistency(self, domain: str) -> list[str]:
        """检查同一域内所有表是否使用了相同的维度定义。"""
        matrix = await self.get_matrix()
        domain_cells = [c for c in matrix if c.domain == domain]

        if len(domain_cells) <= 1:
            return []

        # 比较各维度使用的表集合是否一致
        first_tables = set(domain_cells[0].tables)
        inconsistencies = []
        for cell in domain_cells[1:]:
            if set(cell.tables) != first_tables:
                inconsistencies.append(
                    f"维度 {cell.dimension}: 表集合不一致 ({sorted(first_tables)} vs {sorted(cell.tables)})"
                )
        return inconsistencies

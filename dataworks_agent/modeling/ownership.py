"""OwnershipTracker — 表级和字段级产权记录。"""

from __future__ import annotations

import logging

from dataworks_agent.schemas import OwnershipRecord

logger = logging.getLogger(__name__)


class OwnershipTracker:
    """产权管理 — 记录每张表/字段的创建者和变更历史。"""

    async def record_table_creation(self, table: str, created_by_ip: str) -> None:
        """新建表时记录产权。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import OwnershipRecordModel

        with SessionLocal() as db:
            record = OwnershipRecordModel(
                table_name=table,
                created_by_ip=created_by_ip,
                change_type="create",
            )
            db.add(record)
            db.commit()

    async def record_field_change(
        self, table: str, field: str, change_type: str, changed_by_ip: str
    ) -> None:
        """字段变更时追记。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import OwnershipRecordModel

        with SessionLocal() as db:
            record = OwnershipRecordModel(
                table_name=table,
                field_name=field,
                last_modified_by_ip=changed_by_ip,
                change_type=change_type,
            )
            db.add(record)
            db.commit()

    async def get_table_owners(
        self, table: str, limit: int = 50, offset: int = 0
    ) -> list[OwnershipRecord]:
        """查询表的产权历史。"""
        from sqlalchemy import select

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import OwnershipRecordModel

        with SessionLocal() as db:
            stmt = (
                select(OwnershipRecordModel)
                .where(OwnershipRecordModel.table_name == table)
                .order_by(OwnershipRecordModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = db.execute(stmt).scalars().all()
            return [
                OwnershipRecord(
                    table_name=r.table_name,
                    field_name=r.field_name,
                    created_by_ip=r.created_by_ip,
                    last_modified_by_ip=r.last_modified_by_ip,
                    business_owner=r.business_owner,
                    change_type=r.change_type,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    async def get_all_owners(self, limit: int = 50, offset: int = 0) -> list[OwnershipRecord]:
        """查询全部产权记录。"""
        from sqlalchemy import select

        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import OwnershipRecordModel

        with SessionLocal() as db:
            stmt = (
                select(OwnershipRecordModel)
                .order_by(OwnershipRecordModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = db.execute(stmt).scalars().all()
            return [
                OwnershipRecord(
                    table_name=r.table_name,
                    field_name=r.field_name,
                    created_by_ip=r.created_by_ip,
                    last_modified_by_ip=r.last_modified_by_ip,
                    business_owner=r.business_owner,
                    change_type=r.change_type,
                    created_at=r.created_at,
                )
                for r in rows
            ]

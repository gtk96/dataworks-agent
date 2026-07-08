"""产物管理 API — DDL 查询和下载。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/ddl")
async def list_artifacts(
    table_name: str | None = None,
    layer: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """跨任务查询生成的 DDL（按层/来源表/目标表筛选）。"""
    from sqlalchemy import func, select

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ArtifactModel

    with SessionLocal() as db:
        stmt = select(ArtifactModel)
        count_stmt = select(func.count()).select_from(ArtifactModel)
        if table_name:
            stmt = stmt.where(ArtifactModel.table_name == table_name)
            count_stmt = count_stmt.where(ArtifactModel.table_name == table_name)
        if layer:
            stmt = stmt.where(ArtifactModel.table_name.startswith(f"{layer.lower()}_"))
            count_stmt = count_stmt.where(ArtifactModel.table_name.startswith(f"{layer.lower()}_"))

        total = db.execute(count_stmt).scalar() or 0
        stmt = stmt.order_by(ArtifactModel.created_at.desc()).offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        return {
            "artifacts": [
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "table_name": r.table_name,
                    "ddl_dev": r.ddl_dev[:500] if r.ddl_dev else "",
                    "ddl_prod": r.ddl_prod[:500] if r.ddl_prod else "",
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("/ddl/{artifact_id}")
async def get_artifact(artifact_id: int):
    """获取单条 DDL 内容。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ArtifactModel

    with SessionLocal() as db:
        r = db.get(ArtifactModel, artifact_id)
        if not r:
            raise HTTPException(status_code=404, detail="产物不存在")
        return {
            "id": r.id,
            "task_id": r.task_id,
            "table_name": r.table_name,
            "ddl_dev": r.ddl_dev,
            "ddl_prod": r.ddl_prod,
            "dml": r.dml,
            "schedule_config": r.schedule_config_json,
            "created_at": r.created_at,
        }

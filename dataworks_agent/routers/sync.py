"""双环境同步 API — dev→prod 表结构+数据同步。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from dataworks_agent.schemas import SyncExecuteRequest, require_write_access

router = APIRouter()


@router.get("/tables")
async def list_sync_tables(
    layer: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
):
    """获取可同步表列表（所有表定义，支持按层/关键字过滤 + 分页）。"""
    from sqlalchemy import func, select

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import TableDefinitionModel

    with SessionLocal() as db:
        # 总数
        count_q = select(func.count()).select_from(TableDefinitionModel)
        if layer:
            count_q = count_q.where(TableDefinitionModel.layer == layer)
        if search:
            count_q = count_q.where(TableDefinitionModel.table_name.ilike(f"%{search}%"))
        total = db.execute(count_q).scalar() or 0

        # 分页查询
        stmt = select(TableDefinitionModel)
        if layer:
            stmt = stmt.where(TableDefinitionModel.layer == layer)
        if search:
            stmt = stmt.where(TableDefinitionModel.table_name.ilike(f"%{search}%"))
        stmt = (
            stmt.order_by(TableDefinitionModel.table_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        tables = db.execute(stmt).scalars().all()
        return {
            "tables": [
                {"table_name": t.table_name, "schema": t.schema_name, "layer": t.layer}
                for t in tables
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.post("/diff")
async def get_diff(body: SyncExecuteRequest):
    """获取 dev/prod DDL 差异对比。"""
    from dataworks_agent.modeling.sync_engine import SyncEngine

    engine = SyncEngine()
    result = await engine.sync_table(body.table_name)
    return result.model_dump()


@router.post("/execute")
async def execute_sync(
    body: SyncExecuteRequest,
    request: Request,
    _auth=Depends(require_write_access),  # noqa: B008
):
    """执行同步至生产（需 L2+ 权限）。

    注意: 当前版本无 Depends(get_current_user) 鉴权 —
    未来需增加用户认证中间件后补上。
    """
    from dataworks_agent.modeling.sync_engine import (
        SyncCatastrophicError,
        SyncEngine,
        SyncRollbackError,
    )
    from dataworks_agent.services.audit import audit_log

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    audit_log("sync_execute_start", ip=client_ip, table_name=body.table_name)

    engine = SyncEngine()
    try:
        result = await engine.execute_sync(body.table_name)
        audit_log(
            "sync_execute_done",
            ip=client_ip,
            table_name=body.table_name,
            status=result.get("status", ""),
        )
        return result
    except SyncRollbackError as e:
        audit_log(
            "sync_execute_rollback", ip=client_ip, table_name=body.table_name, error=str(e)[:200]
        )
        raise HTTPException(status_code=500, detail=f"同步失败(已回滚DDL): {e}") from e
    except SyncCatastrophicError as e:
        audit_log(
            "sync_execute_catastrophic",
            ip=client_ip,
            table_name=body.table_name,
            error=str(e)[:200],
        )
        raise HTTPException(status_code=500, detail=f"同步灾难性失败,需人工介入: {e}") from e


@router.get("/history")
async def sync_history(limit: int = 50):
    """同步历史记录。"""
    from sqlalchemy import select

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import SyncJobModel

    with SessionLocal() as db:
        stmt = select(SyncJobModel).order_by(SyncJobModel.created_at.desc()).limit(limit)
        jobs = db.execute(stmt).scalars().all()
        return {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "source_table": j.source_table,
                    "target_table": j.target_table,
                    "status": j.status,
                    "error": j.execution_log if j.status and j.status != "success" else "",
                    "created_at": j.created_at,
                }
                for j in jobs
            ]
        }

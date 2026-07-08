"""Reconciliation API — 待协调任务列表 + 人工处置。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dataworks_agent.schemas import ReconciliationDisposeRequest, require_write_access

router = APIRouter()


@router.get("/tasks")
async def list_reconciliation_tasks():
    """列出待协调任务（status=intent 超过 5 分钟的步骤日志）。"""
    from dataworks_agent.task_engine.intent_logger import detect_dangling_intents

    dangling = await detect_dangling_intents()
    return {"tasks": dangling}


@router.post("/dispose")
async def dispose_reconciliation(
    body: ReconciliationDisposeRequest,
    _auth=Depends(require_write_access),  # noqa: B008
):
    """人工处置: retry / confirm_success / confirm_failed。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import ReconciliationTaskModel
    from dataworks_agent.services.audit import audit_log

    with SessionLocal() as db:
        rec = db.get(ReconciliationTaskModel, body.task_id)
        if not rec:
            raise HTTPException(status_code=404, detail="协调任务不存在")

        rec.disposition = body.action
        db.commit()

    audit_log("reconciliation_dispose", task_id=body.task_id, action=body.action)

    return {"task_id": body.task_id, "action": body.action}

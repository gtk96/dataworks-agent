"""Reconciliation API — 待协调任务列表 + 人工处置。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dataworks_agent.schemas import ReconciliationDisposeRequest, require_write_access

router = APIRouter()


@router.get("/tasks")
async def list_reconciliation_tasks():
    """列出待协调任务（status=intent 的步骤日志）。"""
    from dataworks_agent.task_engine.intent_logger import detect_dangling_intents

    dangling = await detect_dangling_intents()
    return {"tasks": dangling}


@router.post("/dispose")
async def dispose_reconciliation(
    body: ReconciliationDisposeRequest,
    _auth=Depends(require_write_access),  # noqa: B008
):
    """人工处置 dangling intent: retry / confirm_success / confirm_failed。"""
    from dataworks_agent.services.audit import audit_log
    from dataworks_agent.task_engine.intent_logger import dispose_intent

    result = await dispose_intent(body.intent_id, body.action)
    if not result:
        raise HTTPException(status_code=404, detail="协调记录不存在或已处置")

    audit_log(
        "reconciliation_dispose",
        intent_id=body.intent_id,
        task_id=result["task_id"],
        action=body.action,
    )
    return result

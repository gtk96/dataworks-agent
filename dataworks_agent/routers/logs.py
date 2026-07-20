"""日志 API — 任务日志与会话事件查询。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from dataworks_agent.agent.conversation_events import ConversationEventRecorder
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import TaskStepLogModel

router = APIRouter()


def _parse_utc(value: str, *, parameter: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid ISO datetime: {parameter}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _matches_exact_filters(
    item: dict[str, Any],
    filters: dict[str, str | None],
) -> bool:
    return all(
        expected is None or item.get(field) == expected for field, expected in filters.items()
    )


@router.get("")
async def query_logs(
    task_id: str = Query(None),
    level: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """查询任务日志（按 task_id/level 筛选）。"""
    from sqlalchemy import select

    with SessionLocal() as db:
        stmt = select(TaskStepLogModel).order_by(TaskStepLogModel.created_at.desc()).limit(limit)

        if task_id:
            stmt = stmt.where(TaskStepLogModel.task_id == task_id)
        if level:
            stmt = stmt.where(TaskStepLogModel.error.like(f"%{level}%"))

        logs = db.execute(stmt).scalars().all()

        return {
            "logs": [
                {
                    "id": entry.id,
                    "task_id": entry.task_id,
                    "step_name": entry.step_name,
                    "status": entry.status,
                    "operation": entry.intent_operation,
                    "target": entry.intent_target,
                    "error": entry.error,
                    "duration_ms": entry.duration_ms,
                    "created_at": entry.created_at,
                }
                for entry in logs
            ]
        }


@router.get("/conversations")
async def query_conversation_events(
    conversation_id: str,
    request_id: str | None = None,
    turn_id: str | None = None,
    interaction_id: str | None = None,
    event: str | None = None,
    level: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
):
    """按关联 ID、事件类型、级别和 UTC 时间范围精确查询会话事件。"""
    range_start = _parse_utc(created_from, parameter="created_from") if created_from else None
    range_end = _parse_utc(created_to, parameter="created_to") if created_to else None
    if range_start and range_end and range_start > range_end:
        raise HTTPException(status_code=422, detail="created_from must not be after created_to")

    filters = {
        "request_id": request_id,
        "turn_id": turn_id,
        "interaction_id": interaction_id,
        "event": event,
        "level": level,
    }
    matched: list[dict[str, Any]] = []
    for item in ConversationEventRecorder().events(conversation_id=conversation_id):
        if not _matches_exact_filters(item, filters):
            continue
        if range_start or range_end:
            try:
                created_at = _parse_utc(str(item["created_at"]), parameter="event.created_at")
            except (KeyError, TypeError):
                continue
            if range_start and created_at < range_start:
                continue
            if range_end and created_at > range_end:
                continue
        matched.append(item)
        if len(matched) >= limit:
            break

    return {"events": matched}

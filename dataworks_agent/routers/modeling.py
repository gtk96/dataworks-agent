"""建模任务 API — CRUD + SSE 实时进度。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel, TaskStepLogModel
from dataworks_agent.modeling.engine import ModelingEngine
from dataworks_agent.schemas import (
    CreateTaskRequest,
    SSEEvent,
    TaskDetailResponse,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter()
engine = ModelingEngine()
# 幂等缓存: {key: (task_id, expiry_timestamp)}
_idempotency_cache: dict[str, tuple[str, float]] = {}
_IDEMPOTENCY_TTL = 600.0  # 10 分钟过期


def _invalidate_tasks_cache() -> None:
    """T1: 任务列表写操作后使 tasks:* 缓存失效，避免最多 30s 陈旧。

    缓存键形如 tasks:{client_ip}:scope:...，invalidate_by_source("tasks")
    按 "tasks:" 前缀批量清除（见 cache/manager.py:invalidate_by_source）。
    """
    from dataworks_agent.cache import get_cache_manager

    get_cache_manager().invalidate_by_source("tasks")


async def _publish_task_status_changed(task_id: str, status: str) -> None:
    """发布任务状态变更事件，驱动 dashboard WS 实时刷新（与状态机链路一致）。

    使用 publish_async 以正确 await 订阅回调（_broadcast_task_status 是 async）。
    """
    import time

    from dataworks_agent.cache.events import Event, EventType, get_event_bus

    await get_event_bus().publish_async(
        Event(
            event_type=EventType.TASK_STATUS_CHANGED,
            source="task",
            data={"task_id": task_id, "status": status, "timestamp": time.time()},
        )
    )


@router.post("/tasks", status_code=202)
async def create_task(
    request: Request,
    body: CreateTaskRequest,
    x_idempotency_key: str = Header(None, alias="X-Idempotency-Key"),
):
    """创建建模任务 — 返回 202 + task_id。"""
    import time

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")

    if x_idempotency_key:
        now = time.monotonic()
        entry = _idempotency_cache.get(x_idempotency_key)
        if entry:
            cached_task_id, expiry = entry
            if now < expiry:
                return {"task_id": cached_task_id, "message": "重复请求"}
            else:
                del _idempotency_cache[x_idempotency_key]

    try:
        task_id = await engine.create_task(body, client_ip)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if x_idempotency_key:
        _idempotency_cache[x_idempotency_key] = (task_id, time.monotonic() + _IDEMPOTENCY_TTL)

    return {"task_id": task_id, "status": "pending"}


@router.get("/tasks")
async def list_tasks(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    layer: str | None = None,
    node_type: str | None = None,
    scope: str = Query(default="mine", description="mine=仅自己的, all=全部"),
):
    """获取任务列表 — 默认按 IP 过滤，scope=all 查看全部。"""
    from dataworks_agent.cache import get_cache_manager

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    cache = get_cache_manager()

    # 生成缓存键
    cache_key = f"tasks:{client_ip}:{scope}:{status or ''}:{layer or ''}:{node_type or ''}:{page}:{page_size}"

    # 尝试从缓存获取
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with SessionLocal() as db:
        from sqlalchemy import func

        from dataworks_agent.services.task_classification import (
            infer_node_type,
            infer_node_type_sql,
        )

        # v15 F2-5: node_type 过滤 + 分页全部下推 SQL。
        # infer_node_type_sql() 把同规则编译成 CASE WHEN，让 SQL 能直接
        # 过滤 node_type，无需先全表拉到 Python 内存。

        base = select(ModelingTaskModel)
        if scope != "all":
            base = base.where(ModelingTaskModel.created_by_ip == client_ip)
        if status:
            base = base.where(ModelingTaskModel.status == status)
        if layer:
            base = base.where(ModelingTaskModel.target_layer == layer)
        if node_type:
            base = base.where(infer_node_type_sql() == node_type.lower())

        # 先 count 总数（与 base WHERE 同步）
        count_q = select(func.count(ModelingTaskModel.task_id))
        if scope != "all":
            count_q = count_q.where(ModelingTaskModel.created_by_ip == client_ip)
        if status:
            count_q = count_q.where(ModelingTaskModel.status == status)
        if layer:
            count_q = count_q.where(ModelingTaskModel.target_layer == layer)
        if node_type:
            count_q = count_q.where(infer_node_type_sql() == node_type.lower())
        total = db.execute(count_q).scalar() or 0

        offset = (page - 1) * page_size
        page_stmt = (
            base.order_by(ModelingTaskModel.created_at.desc()).offset(offset).limit(page_size)
        )
        page_tasks = db.execute(page_stmt).scalars().all()

        result = TaskListResponse(
            tasks=[
                TaskResponse(
                    task_id=t.task_id,
                    status=t.status,
                    target_table=t.target_table,
                    target_layer=t.target_layer,
                    node_type=infer_node_type(t),
                    created_by_ip=t.created_by_ip or "",
                    created_at=t.created_at,
                    updated_at=t.updated_at or "",
                    duration_seconds=t.duration_seconds or 0,
                )
                for t in page_tasks
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

        # 缓存结果（短 TTL，因为数据会变化）
        cache.set(cache_key, result, ttl=30)

        return result


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> TaskDetailResponse:
    """获取任务详情 + 步骤日志。"""
    with SessionLocal() as db:
        task = db.get(ModelingTaskModel, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        step_logs = (
            db.execute(select(TaskStepLogModel).where(TaskStepLogModel.task_id == task_id))
            .scalars()
            .all()
        )

        from dataworks_agent.schemas import ModelingTask, TaskStepLog

        return TaskDetailResponse(
            task=ModelingTask(
                task_id=task.task_id,
                status=task.status,
                source_table=task.source_table,
                target_table=task.target_table,
                target_layer=task.target_layer,
                node_type=task.node_type or "",
                domain=task.domain,
                entity=task.entity,
                update_method=task.update_method,
                ddl_dev=task.ddl_dev,
                ddl_prod=task.ddl_prod,
                dml=task.dml,
                node_uuid=task.node_uuid,
                node_name=task.node_name,
                created_by_ip=task.created_by_ip,
                created_at=task.created_at,
                updated_at=task.updated_at,
                error_message=task.error_message,
                steps=json.loads(task.steps_json) if task.steps_json else [],
                project_id=task.project_id,
            ),
            step_logs=[
                TaskStepLog(
                    task_id=s.task_id,
                    step_name=s.step_name,
                    status=s.status,
                    intent_operation=s.intent_operation,
                    intent_target=s.intent_target,
                    result=json.loads(s.result_json) if s.result_json else {},
                    error=s.error,
                    duration_ms=s.duration_ms,
                    created_at=s.created_at,
                )
                for s in step_logs
            ],
        )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    """取消任务。"""
    from dataworks_agent.services.audit import audit_log

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    with SessionLocal() as db:
        task = db.get(ModelingTaskModel, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        task.status = "cancelled"
        db.commit()
        audit_log("task_cancel", ip=client_ip, task_id=task_id, target_table=task.target_table)
        return {"task_id": task_id, "status": "cancelled"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request):
    """重试失败任务 — 重新执行建模流水线。"""
    import logging

    from dataworks_agent.services.audit import audit_log

    logger = logging.getLogger(__name__)

    with SessionLocal() as db:
        task = db.get(ModelingTaskModel, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status not in ("failed", "cancelled"):
            raise HTTPException(status_code=400, detail=f"任务状态 {task.status} 不可重试")

    client_ip = getattr(request.state, "client_ip", "127.0.0.1")
    logger.info("重试任务: task_id=%s, ip=%s", task_id, client_ip)

    with SessionLocal() as db:
        t = db.get(ModelingTaskModel, task_id)
        dwd_md = (
            json.loads(t.dwd_metadata_json)
            if t.dwd_metadata_json and t.dwd_metadata_json != "{}"
            else None
        )
        body = CreateTaskRequest(
            source_table=t.source_table,
            target_layer=t.target_layer,
            domain=t.domain or "",
            entity=t.entity or "",
            update_method=t.update_method or "full",
            partition_keys=json.loads(t.partition_keys_json) if t.partition_keys_json else ["dt"],
            schedule_config=json.loads(t.schedule_config_json) if t.schedule_config_json else None,
            dwd_metadata=dwd_md,
        )

    new_task_id = await engine.create_task(body, client_ip)
    audit_log("task_retry", ip=client_ip, old_task_id=task_id, new_task_id=new_task_id)
    return {"task_id": new_task_id, "status": "pending", "retried_from": task_id}


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    """SSE 实时进度流。"""

    async def _event_generator():
        # 先检查任务是否存在
        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task:
                yield f"data: {json.dumps({'event': 'error', 'message': '任务不存在'})}\n\n"
                return

            status = task.status

        # 已完成的任务直接返回状态
        if status in ("completed", "failed", "cancelled"):
            yield f"data: {json.dumps({'event': 'done', 'task_id': task_id, 'status': status})}\n\n"
            return

        # 运行中的任务轮询状态
        for _ in range(300):  # 最多 5 分钟
            with SessionLocal() as db:
                task = db.get(ModelingTaskModel, task_id)
                if not task:
                    break
                current = task.status
                steps = json.loads(task.steps_json) if task.steps_json else []
                ddl_dev = task.ddl_dev
                dml = task.dml

            event = SSEEvent(
                event="progress",
                task_id=task_id,
                status=current,
                step=current,
                data={
                    "steps": steps,
                    "ddl_dev": ddl_dev[:500] if ddl_dev else "",
                    "dml": dml[:500] if dml else "",
                },
            )
            yield f"data: {event.model_dump_json()}\n\n"

            if current in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(2)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/preview")
async def preview_ddl(body: CreateTaskRequest, request: Request):
    """Dry-run 预览 — 生成 DDL/DML 但不执行（无副作用）。"""
    try:
        result = await engine.preview_task(body)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return result

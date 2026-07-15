"""Persistent pipeline queue + ODS OSS/Realtime batch APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


@router.get("/batches")
async def list_batches(limit: int = 20):
    """获取所有批次列表。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import PipelineBatchModel

    with SessionLocal() as db:
        from sqlalchemy import desc, select

        stmt = select(PipelineBatchModel).order_by(desc(PipelineBatchModel.created_at)).limit(limit)
        rows = db.execute(stmt).scalars().all()
        return {
            "batches": [
                {
                    "batch_id": r.batch_id,
                    "pipeline_type": r.pipeline_type,
                    "status": r.status,
                    "total_tasks": r.total_tasks,
                    "success_count": r.success_count,
                    "failed_count": r.failed_count,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "total": len(rows),
        }


def _record_pipeline_modeling_task(
    *,
    node_type: str,
    target_table: str,
    source_table: str,
    success: bool,
    client_ip: str,
    node_uuid: str = "",
    error_message: str = "",
) -> None:
    from dataworks_agent.services.task_registry import record_task

    record_task(
        node_type=node_type,
        target_table=target_table,
        source_table=source_table,
        target_layer="ODS",
        status="completed" if success else "failed",
        created_by_ip=client_ip,
        node_uuid=node_uuid,
        error_message=error_message,
    )


class OssSubmission(BaseModel):
    oss_path: str
    target_table: str
    file_format: str = "json"
    wildcard: str = ""
    schedule_type: str = "day"
    source_partition_value: str | None = None
    publish: bool = True


class RealtimeSubmission(BaseModel):
    database_schema: str
    table_name: str
    sync_rows: list[dict] = Field(default_factory=list)
    select_dml: str = ""
    granularity: str = "hour"
    publish: bool = True


class OssBatchRequest(BaseModel):
    submissions: list[OssSubmission]
    node_path_prefix: str = "dataworks_agent/01_ODS"
    run_immediately: bool = True


class RealtimeBatchRequest(BaseModel):
    submissions: list[RealtimeSubmission]
    node_path_prefix: str = "dataworks_agent/01_ODS"
    run_immediately: bool = True


@router.post("/oss/batch")
async def create_oss_batch(req: Request, body: OssBatchRequest):
    """Create OSS import batch; optionally execute tasks inline."""
    from dataworks_agent.services.ods_oss import OssImportPipeline
    from dataworks_agent.services.task_classification import NODE_TYPE_ODPS
    from dataworks_agent.state import app_state
    from dataworks_agent.task_engine.persistent_queue import PersistentPipelineQueue

    # 节点操作优先走 AK/SK 适配器（Task 8b），迁移期缺 AK/SK 时降级回 bff
    bff = getattr(app_state, "_node_client", None) or getattr(app_state, "_bff_client", None)
    if body.run_immediately and not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")

    client_ip = getattr(req.state, "client_ip", "127.0.0.1")
    queue = PersistentPipelineQueue()
    batch = queue.create_batch(
        pipeline_type="ods_oss",
        submissions=[s.model_dump() for s in body.submissions],
        created_by_ip=client_ip,
    )

    worker_id = f"worker_{client_ip}"
    results: list[dict] = []

    if body.run_immediately and bff:
        pipeline = OssImportPipeline(bff)
        total = len(body.submissions)
        for idx, submission in enumerate(body.submissions):
            claimed = queue.claim_next(worker_id)
            if not claimed:
                break
            task_id = claimed["task_id"]
            batch_id = claimed["batch_id"]
            try:
                run_result = await pipeline.run(
                    oss_path=submission.oss_path,
                    target_table=submission.target_table,
                    file_format=submission.file_format,
                    wildcard=submission.wildcard,
                    schedule_type=submission.schedule_type,
                    node_path_prefix=body.node_path_prefix,
                    task_index=idx,
                    total_tasks=total,
                    publish=submission.publish,
                    source_partition_value=submission.source_partition_value,
                )
                if run_result.get("success"):
                    queue.complete_task(
                        task_id,
                        worker_id=worker_id,
                        result=run_result,
                        node_uuid=run_result.get("node_uuid", ""),
                    )
                    queue.log_step(
                        task_id=task_id,
                        batch_id=batch_id,
                        step_name="execute",
                        step_seq=1,
                        status="success",
                        detail={"target_table": submission.target_table},
                    )
                else:
                    queue.fail_task(
                        task_id,
                        worker_id=worker_id,
                        error=str(run_result.get("steps", {})),
                        result=run_result,
                    )
                _record_pipeline_modeling_task(
                    node_type=NODE_TYPE_ODPS,
                    target_table=submission.target_table,
                    source_table=submission.oss_path,
                    success=bool(run_result.get("success")),
                    client_ip=client_ip,
                    node_uuid=str(run_result.get("node_uuid") or ""),
                    error_message=""
                    if run_result.get("success")
                    else str(run_result.get("steps", ""))[:500],
                )
                results.append({"task_id": task_id, **run_result})
            except Exception as exc:
                queue.fail_task(task_id, worker_id=worker_id, error=str(exc))
                _record_pipeline_modeling_task(
                    node_type=NODE_TYPE_ODPS,
                    target_table=submission.target_table,
                    source_table=submission.oss_path,
                    success=False,
                    client_ip=client_ip,
                    error_message=str(exc)[:500],
                )
                results.append({"task_id": task_id, "success": False, "error": str(exc)})

    snapshot = queue.get_batch(batch["batch_id"])
    return {
        "status": "ok" if snapshot and snapshot["status"] != "failed" else "partial",
        "batch_id": batch["batch_id"],
        "task_count": batch["task_count"],
        "results": results,
        "batch": snapshot,
    }


@router.post("/realtime/batch")
async def create_realtime_batch(req: Request, body: RealtimeBatchRequest):
    """Create realtime ODS batch; optionally execute tasks inline."""
    from dataworks_agent.services.ods_realtime import RealtimeSyncPipeline
    from dataworks_agent.services.task_classification import NODE_TYPE_DI
    from dataworks_agent.state import app_state
    from dataworks_agent.task_engine.persistent_queue import PersistentPipelineQueue

    # 节点操作优先走 AK/SK 适配器（Task 8b），迁移期缺 AK/SK 时降级回 bff
    bff = getattr(app_state, "_node_client", None) or getattr(app_state, "_bff_client", None)
    if body.run_immediately and not bff:
        raise HTTPException(status_code=503, detail="BFF 不可用")

    client_ip = getattr(req.state, "client_ip", "127.0.0.1")
    queue = PersistentPipelineQueue()
    batch = queue.create_batch(
        pipeline_type="ods_realtime",
        submissions=[s.model_dump() for s in body.submissions],
        created_by_ip=client_ip,
    )

    worker_id = f"worker_{client_ip}"
    results: list[dict] = []

    if body.run_immediately and bff:
        pipeline = RealtimeSyncPipeline(bff)
        for submission in body.submissions:
            claimed = queue.claim_next(worker_id)
            if not claimed:
                break
            task_id = claimed["task_id"]
            batch_id = claimed["batch_id"]
            try:
                run_result = await pipeline.run(
                    database_schema=submission.database_schema,
                    table_name=submission.table_name,
                    sync_rows=submission.sync_rows,
                    select_dml=submission.select_dml or None,
                    granularity=submission.granularity,
                    node_path_prefix=body.node_path_prefix,
                    publish=submission.publish,
                )
                if run_result.get("success"):
                    queue.complete_task(
                        task_id,
                        worker_id=worker_id,
                        result=run_result,
                        node_uuid=run_result.get("node_uuid", ""),
                    )
                    queue.log_step(
                        task_id=task_id,
                        batch_id=batch_id,
                        step_name="execute",
                        step_seq=1,
                        status="success",
                    )
                else:
                    queue.fail_task(
                        task_id, worker_id=worker_id, error=str(run_result.get("steps"))
                    )
                _record_pipeline_modeling_task(
                    node_type=NODE_TYPE_DI,
                    target_table=run_result.get("target_table")
                    or f"ods_mc_{submission.database_schema}__{submission.table_name}_{submission.granularity}",
                    source_table=f"{submission.database_schema}.{submission.table_name}",
                    success=bool(run_result.get("success")),
                    client_ip=client_ip,
                    node_uuid=str(run_result.get("node_uuid") or ""),
                    error_message=""
                    if run_result.get("success")
                    else str(run_result.get("steps", ""))[:500],
                )
                results.append({"task_id": task_id, **run_result})
            except Exception as exc:
                queue.fail_task(task_id, worker_id=worker_id, error=str(exc))
                _record_pipeline_modeling_task(
                    node_type=NODE_TYPE_DI,
                    target_table=f"ods_mc_{submission.database_schema}__{submission.table_name}_{submission.granularity}",
                    source_table=f"{submission.database_schema}.{submission.table_name}",
                    success=False,
                    client_ip=client_ip,
                    error_message=str(exc)[:500],
                )
                results.append({"task_id": task_id, "success": False, "error": str(exc)})

    snapshot = queue.get_batch(batch["batch_id"])
    return {
        "status": "ok" if snapshot and snapshot["status"] != "failed" else "partial",
        "batch_id": batch["batch_id"],
        "task_count": batch["task_count"],
        "results": results,
        "batch": snapshot,
    }


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str):
    """Get batch status, tasks, and step logs."""
    from dataworks_agent.task_engine.persistent_queue import PersistentPipelineQueue

    snapshot = PersistentPipelineQueue().get_batch(batch_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="批次不存在")
    return snapshot


@router.post("/preview/oss-sql")
async def preview_oss_sql(body: OssSubmission):
    """Preview external-table-to-ODS SQL without creating nodes."""
    from dataworks_agent.services.ods_oss import (
        build_ods_extract_sql,
        ods_table_name,
        parse_oss_path,
        validate_oss_config,
    )

    errors = validate_oss_config(body.oss_path, body.target_table, body.file_format)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    location = parse_oss_path(body.oss_path)
    source_name = str(location["object_key"] or "").rstrip("/").rsplit("/", 1)[-1]
    if "." in source_name and not location.get("is_prefix"):
        source_name = source_name.rsplit(".", 1)[0]
    try:
        expected_table = ods_table_name(
            source_name, body.schedule_type if body.schedule_type in {"day", "hour"} else "day"
        )
        if body.target_table != expected_table:
            raise ValueError(f"target_table must be {expected_table}")
        sql = build_ods_extract_sql(
            source_table=source_name,
            target_table=body.target_table,
            granularity=body.schedule_type,
            source_partition_value=body.source_partition_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    return {
        "status": "ok",
        "sql": sql,
        "source_table": source_name,
        "target_table": body.target_table,
    }


@router.post("/preview/realtime")
async def preview_realtime(body: RealtimeSubmission):
    """Preview realtime preprocess + SQL without deploying."""
    from dataworks_agent.config import settings
    from dataworks_agent.services.ods_realtime import (
        extract_fields_from_select_dml,
        generate_insert_sql,
        preprocess_realtime_task,
    )

    prep = preprocess_realtime_task(
        database_schema=body.database_schema,
        table_name=body.table_name,
        sync_rows=body.sync_rows,
        granularity=body.granularity,
    )
    if not prep.get("success"):
        raise HTTPException(status_code=422, detail=prep.get("error"))

    fields = extract_fields_from_select_dml(body.select_dml or None)
    sql = generate_insert_sql(
        prep["ods_table_name"],
        prep["delta_table"],
        fields,
        settings.dataworks_prod_schema,
        settings.dataworks_dev_schema,
    )
    return {"status": "ok", "preprocess": prep, "fields": fields, "sql": sql}

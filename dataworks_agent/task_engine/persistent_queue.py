"""SQLite-backed persistent pipeline queue with lease/claim."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import PipelineBatchModel, PipelineStepLogModel, PipelineTaskModel

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class PersistentPipelineQueue:
    """Durable batch/task queue — survives process restarts (SQLite)."""

    def create_batch(
        self,
        *,
        pipeline_type: str,
        submissions: list[dict[str, Any]],
        created_by_ip: str = "",
    ) -> dict[str, Any]:
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        task_ids: list[str] = []

        with SessionLocal() as db:
            batch = PipelineBatchModel(
                batch_id=batch_id,
                pipeline_type=pipeline_type,
                status="pending",
                total_tasks=len(submissions),
                created_by_ip=created_by_ip,
            )
            db.add(batch)

            for submission in submissions:
                task_id = f"ptask_{uuid.uuid4().hex[:12]}"
                task_ids.append(task_id)
                db.add(
                    PipelineTaskModel(
                        task_id=task_id,
                        batch_id=batch_id,
                        pipeline_type=pipeline_type,
                        status="pending",
                        target_table=str(submission.get("target_table") or ""),
                        payload_json=json.dumps(submission, ensure_ascii=False),
                    )
                )
            db.commit()

        return {"batch_id": batch_id, "task_ids": task_ids, "task_count": len(task_ids)}

    def claim_next(self, worker_id: str, *, lease_seconds: int = 300) -> dict[str, Any] | None:
        """Claim the oldest pending/reclaimable task."""
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        now_iso = now.isoformat()

        with SessionLocal() as db:
            stmt = (
                select(PipelineTaskModel)
                .where(PipelineTaskModel.status.in_(["pending", "running"]))
                .order_by(PipelineTaskModel.created_at.asc())
            )
            tasks = db.execute(stmt).scalars().all()

            for task in tasks:
                if task.status == "running" and task.lease_until and task.lease_until > now_iso:
                    continue
                task.status = "running"
                task.lease_owner = worker_id
                task.lease_until = lease_until
                task.updated_at = now_iso
                db.commit()
                return {
                    "task_id": task.task_id,
                    "batch_id": task.batch_id,
                    "pipeline_type": task.pipeline_type,
                    "target_table": task.target_table,
                    "payload": json.loads(task.payload_json or "{}"),
                }
        return None

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: int = 300) -> bool:
        lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
        with SessionLocal() as db:
            task = db.get(PipelineTaskModel, task_id)
            if not task or task.lease_owner != worker_id:
                return False
            task.lease_until = lease_until
            task.updated_at = _utc_now()
            db.commit()
            return True

    def complete_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        result: dict[str, Any] | None = None,
        node_uuid: str = "",
    ) -> None:
        with SessionLocal() as db:
            task = db.get(PipelineTaskModel, task_id)
            if not task:
                return
            if task.lease_owner and task.lease_owner != worker_id:
                raise PermissionError(f"task {task_id} leased by {task.lease_owner}")

            task.status = "success"
            task.result_json = json.dumps(result or {}, ensure_ascii=False)
            task.node_uuid = node_uuid or task.node_uuid
            task.lease_owner = ""
            task.lease_until = ""
            task.updated_at = _utc_now()
            self._refresh_batch_counts(db, task.batch_id)
            db.commit()

    def fail_task(
        self,
        task_id: str,
        *,
        worker_id: str,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        with SessionLocal() as db:
            task = db.get(PipelineTaskModel, task_id)
            if not task:
                return
            if task.lease_owner and task.lease_owner != worker_id:
                raise PermissionError(f"task {task_id} leased by {task.lease_owner}")

            task.status = "failed"
            task.error_message = error[:2000]
            task.result_json = json.dumps(result or {}, ensure_ascii=False)
            task.lease_owner = ""
            task.lease_until = ""
            task.updated_at = _utc_now()
            self._refresh_batch_counts(db, task.batch_id)
            db.commit()

    def log_step(
        self,
        *,
        task_id: str,
        batch_id: str,
        step_name: str,
        step_seq: int,
        status: str,
        detail: dict[str, Any] | None = None,
        error_message: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        with SessionLocal() as db:
            db.add(
                PipelineStepLogModel(
                    task_id=task_id,
                    batch_id=batch_id,
                    step_name=step_name,
                    step_seq=step_seq,
                    status=status,
                    detail_json=json.dumps(detail or {}, ensure_ascii=False),
                    error_message=error_message[:2000],
                    elapsed_ms=elapsed_ms,
                )
            )
            task = db.get(PipelineTaskModel, task_id)
            if task:
                task.phase = step_name
                task.phase_seq = step_seq
                task.updated_at = _utc_now()
            db.commit()

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            batch = db.get(PipelineBatchModel, batch_id)
            if not batch:
                return None
            tasks = (
                db.execute(select(PipelineTaskModel).where(PipelineTaskModel.batch_id == batch_id))
                .scalars()
                .all()
            )
            logs = (
                db.execute(
                    select(PipelineStepLogModel).where(PipelineStepLogModel.batch_id == batch_id)
                )
                .scalars()
                .all()
            )
            return {
                "batch_id": batch.batch_id,
                "pipeline_type": batch.pipeline_type,
                "status": batch.status,
                "total_tasks": batch.total_tasks,
                "success_count": batch.success_count,
                "failed_count": batch.failed_count,
                "skipped_count": batch.skipped_count,
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "status": t.status,
                        "target_table": t.target_table,
                        "phase": t.phase,
                        "error_message": t.error_message,
                        "node_uuid": t.node_uuid,
                    }
                    for t in tasks
                ],
                "step_logs": [
                    {
                        "task_id": entry.task_id,
                        "step_name": entry.step_name,
                        "status": entry.status,
                        "error_message": entry.error_message,
                    }
                    for entry in logs
                ],
            }

    @staticmethod
    def _refresh_batch_counts(db, batch_id: str) -> None:
        tasks = (
            db.execute(select(PipelineTaskModel).where(PipelineTaskModel.batch_id == batch_id))
            .scalars()
            .all()
        )
        success = sum(1 for t in tasks if t.status == "success")
        failed = sum(1 for t in tasks if t.status == "failed")
        skipped = sum(1 for t in tasks if t.status == "skipped")
        pending = sum(1 for t in tasks if t.status in {"pending", "running"})
        batch = db.get(PipelineBatchModel, batch_id)
        if not batch:
            return
        batch.success_count = success
        batch.failed_count = failed
        batch.skipped_count = skipped
        if pending:
            batch.status = "running"
        elif failed and success:
            batch.status = "partial_failed"
        elif failed:
            batch.status = "failed"
        else:
            batch.status = "completed"
        batch.updated_at = _utc_now()

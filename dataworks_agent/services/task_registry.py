"""Persist workspace / pipeline operations into modeling_tasks for dashboard tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel
from dataworks_agent.services.task_classification import (
    NODE_TYPE_DI,
    NODE_TYPE_HOLO,
    NODE_TYPE_ODPS,
)


def record_task(
    *,
    node_type: str,
    target_table: str,
    source_table: str = "",
    target_layer: str = "ODS",
    status: str = "completed",
    created_by_ip: str = "",
    node_uuid: str = "",
    node_name: str = "",
    error_message: str = "",
    task_id: str | None = None,
) -> str:
    """Insert a modeling_tasks row for DI / Holo / ODPS operations."""
    prefix = {
        NODE_TYPE_HOLO: "holo",
        NODE_TYPE_DI: "di",
        NODE_TYPE_ODPS: "odps",
    }.get(node_type, node_type.replace("-", "_") or "task")
    task_id = task_id or f"{prefix}_{uuid.uuid4().hex[:10]}"
    now = datetime.now(UTC).isoformat()

    with SessionLocal() as db:
        db.add(
            ModelingTaskModel(
                task_id=task_id,
                status=status,
                created_by_ip=created_by_ip,
                source_table=source_table,
                target_table=target_table,
                target_layer=target_layer,
                node_type=node_type,
                node_uuid=node_uuid,
                node_name=node_name or target_table,
                error_message=error_message,
                created_at=now,
                updated_at=now,
                duration_seconds=0.0,
            )
        )
        db.commit()

    return task_id

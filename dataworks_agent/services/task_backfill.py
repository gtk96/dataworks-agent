"""Backfill node_type on legacy modeling_tasks rows."""

from __future__ import annotations

import logging

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel
from dataworks_agent.services.task_classification import infer_node_type

logger = logging.getLogger(__name__)


def backfill_node_types(force: bool = False) -> int:
    """Persist inferred node_type for rows missing it. Returns updated count."""
    updated = 0
    with SessionLocal() as db:
        query = db.query(ModelingTaskModel)
        if not force:
            query = query.filter(
                (ModelingTaskModel.node_type == "") | (ModelingTaskModel.node_type.is_(None))
            )
        for task in query.all():
            inferred = infer_node_type(task)
            if (force or not (task.node_type or "").strip()) and task.node_type != inferred:
                task.node_type = inferred
                updated += 1
        if updated:
            db.commit()
            logger.info("Backfilled node_type on %d modeling_tasks rows", updated)
    return updated

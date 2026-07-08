"""SQLite persistent pipeline queue tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dataworks_agent.db.database import Base
from dataworks_agent.task_engine.persistent_queue import PersistentPipelineQueue


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    db_file = tmp_path / "pipeline_test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(
        "dataworks_agent.task_engine.persistent_queue.SessionLocal", session_factory
    )
    yield PersistentPipelineQueue()
    engine.dispose()


class TestPersistentPipelineQueue:
    def test_create_and_get_batch(self, queue: PersistentPipelineQueue) -> None:
        batch = queue.create_batch(
            pipeline_type="ods_oss",
            submissions=[{"target_table": "ods_oss_a_day", "oss_path": "oss://b/p/"}],
            created_by_ip="127.0.0.1",
        )
        snapshot = queue.get_batch(batch["batch_id"])
        assert snapshot is not None
        assert snapshot["total_tasks"] == 1
        assert snapshot["tasks"][0]["target_table"] == "ods_oss_a_day"

    def test_claim_complete_updates_batch(self, queue: PersistentPipelineQueue) -> None:
        batch = queue.create_batch(
            pipeline_type="ods_oss",
            submissions=[{"target_table": "t1"}],
        )
        claimed = queue.claim_next("worker-1")
        assert claimed is not None
        queue.complete_task(claimed["task_id"], worker_id="worker-1", result={"ok": True})
        snapshot = queue.get_batch(batch["batch_id"])
        assert snapshot["status"] == "completed"
        assert snapshot["success_count"] == 1

    def test_fail_task_marks_batch_failed(self, queue: PersistentPipelineQueue) -> None:
        batch = queue.create_batch(
            pipeline_type="ods_realtime",
            submissions=[{"target_table": "t1"}],
        )
        claimed = queue.claim_next("worker-1")
        assert claimed is not None
        queue.fail_task(claimed["task_id"], worker_id="worker-1", error="boom")
        snapshot = queue.get_batch(batch["batch_id"])
        assert snapshot["failed_count"] == 1
        assert snapshot["status"] == "failed"

    def test_step_log_persisted(self, queue: PersistentPipelineQueue) -> None:
        batch = queue.create_batch(
            pipeline_type="ods_oss",
            submissions=[{"target_table": "t1"}],
        )
        task_id = batch["task_ids"][0]
        queue.log_step(
            task_id=task_id,
            batch_id=batch["batch_id"],
            step_name="validate",
            step_seq=1,
            status="success",
        )
        snapshot = queue.get_batch(batch["batch_id"])
        assert len(snapshot["step_logs"]) == 1
        assert snapshot["step_logs"][0]["step_name"] == "validate"

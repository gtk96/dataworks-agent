"""Intent dispose unit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dataworks_agent.db.database import Base
from dataworks_agent.db.models import TaskStepLogModel
from dataworks_agent.task_engine import intent_logger as mod
from dataworks_agent.task_engine.intent_logger import dispose_intent, log_intent


@pytest.fixture
def intent_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(mod, "SessionLocal", session_factory)
    yield session_factory
    engine.dispose()


@pytest.mark.asyncio
async def test_dispose_confirm_success(intent_db):
    log_id = await log_intent("task_1", "deploy", "create_node", "node_123")
    result = await dispose_intent(log_id, "confirm_success")
    assert result is not None
    assert result["task_id"] == "task_1"
    assert result["action"] == "confirm_success"

    with intent_db() as db:
        log = db.get(TaskStepLogModel, log_id)
        assert log.status == "completed"


@pytest.mark.asyncio
async def test_dispose_unknown_intent_returns_none(intent_db):
    result = await dispose_intent(999999, "confirm_success")
    assert result is None


@pytest.mark.asyncio
async def test_dispose_already_completed_returns_none(intent_db):
    from dataworks_agent.task_engine.intent_logger import confirm_intent

    log_id = await log_intent("task_2", "deploy", "create_node", "node_456")
    await confirm_intent(log_id, {"ok": True})
    result = await dispose_intent(log_id, "confirm_success")
    assert result is None

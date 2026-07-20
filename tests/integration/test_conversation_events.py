"""Conversation event observability integration tests."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import dataworks_agent.db.models  # noqa: F401
from dataworks_agent.agent.conversation_events import ConversationEventRecorder
from dataworks_agent.db.database import Base
from dataworks_agent.eventlog.store import EventLog


@pytest.fixture
def db_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_event_log_create_run_accepts_caller_run_id(db_session_factory):
    event_log = EventLog(db_session_factory)

    run_id = event_log.create_run(
        "conv-owned-id",
        run_id="turn-owned-id",
        channel="web",
        status="running",
    )

    assert run_id == "turn-owned-id"
    run = event_log.get_run(run_id)
    assert run is not None
    assert run.session_id == "conv-owned-id"
    assert run.status == "running"


def test_recorder_persists_ordered_masked_events(db_session_factory):
    recorder = ConversationEventRecorder(EventLog(db_session_factory))
    trace = recorder.start_turn("conv-log", request_id="req-1", input_text="你好")
    recorder.emit(
        trace,
        "context_loaded",
        state_version_before=2,
        authorization="Bearer secret",
    )
    recorder.emit(trace, "turn_classified", dialogue_action="greeting", confidence=1.0)
    recorder.emit(
        trace,
        "turn_failed",
        Authorization="Bearer top-secret",
        Cookie="session=top-secret",
        generated_sql="SELECT personal_email FROM customer",
    )

    events = recorder.events(conversation_id="conv-log")

    assert [item["event"] for item in events] == [
        "turn_received",
        "context_loaded",
        "turn_classified",
        "turn_failed",
    ]
    assert [item["seq"] for item in events] == sorted(item["seq"] for item in events)
    assert all(item["request_id"] == "req-1" for item in events)
    assert all(item["turn_id"] == trace.turn_id for item in events)
    assert [item["level"] for item in events] == ["INFO", "INFO", "INFO", "ERROR"]
    serialized = json.dumps(events, ensure_ascii=False)
    assert "Bearer secret" not in serialized
    assert "top-secret" not in serialized
    assert "personal_email" not in serialized
    assert "***" in serialized


def test_event_log_allocates_unique_sequences_under_threaded_writes(db_session_factory):
    event_log = EventLog(db_session_factory)
    event_log.create_run("conv-threaded", run_id="turn-threaded")

    def append(index: int):
        return event_log.append(
            run_id="turn-threaded",
            session_id="conv-threaded",
            event_type="probe",
            payload={"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(append, range(40)))

    sequences = [record.seq for record in records]
    assert len(set(sequences)) == 40
    assert sorted(sequences) == list(range(min(sequences), min(sequences) + 40))


def test_recorder_finish_marks_run_and_emits_response(db_session_factory):
    event_log = EventLog(db_session_factory)
    recorder = ConversationEventRecorder(event_log)
    trace = recorder.start_turn("conv-finish", request_id="req-finish")

    recorder.finish(trace, success=False, error_type="RuntimeError", level="ERROR")

    events = recorder.events(conversation_id="conv-finish")
    assert events[-1]["event"] == "response_sent"
    assert events[-1]["outcome"] == "failed"
    assert events[-1]["duration_ms"] >= 0
    assert event_log.get_run(trace.turn_id).status == "failed"


def test_conversation_logs_api_applies_exact_filters_and_utc_range(monkeypatch):
    from dataworks_agent.routers import logs as logs_module

    events = [
        {
            "seq": 1,
            "created_at": "2026-07-18T08:00:00+08:00",
            "event": "workflow_started",
            "conversation_id": "conv-1",
            "request_id": "req-1",
            "turn_id": "turn-1",
            "interaction_id": "int-1",
            "level": "INFO",
        },
        {
            "seq": 2,
            "created_at": "2026-07-18T00:00:00+00:00",
            "event": "workflow_started_extra",
            "conversation_id": "conv-1",
            "request_id": "req-10",
            "turn_id": "turn-10",
            "interaction_id": "int-10",
            "level": "INFO-extra",
        },
        {
            "seq": 3,
            "created_at": "2026-07-18T00:00:01+00:00",
            "event": "workflow_started",
            "conversation_id": "conv-1",
            "request_id": "req-1",
            "turn_id": "turn-1",
            "interaction_id": "int-1",
            "level": "INFO",
        },
    ]

    class FakeRecorder:
        def events(self, *, conversation_id: str):
            assert conversation_id == "conv-1"
            return events

    monkeypatch.setattr(logs_module, "ConversationEventRecorder", FakeRecorder)
    app = FastAPI()
    app.include_router(logs_module.router, prefix="/logs")

    response = TestClient(app).get(
        "/logs/conversations",
        params={
            "conversation_id": "conv-1",
            "request_id": "req-1",
            "turn_id": "turn-1",
            "interaction_id": "int-1",
            "event": "workflow_started",
            "level": "INFO",
            "created_from": "2026-07-18T00:00:00Z",
            "created_to": "2026-07-18T00:00:00+00:00",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"events": [events[0]]}


def test_conversation_logs_api_rejects_invalid_utc_range(monkeypatch):
    from dataworks_agent.routers import logs as logs_module

    class FakeRecorder:
        def events(self, *, conversation_id: str):
            return []

    monkeypatch.setattr(logs_module, "ConversationEventRecorder", FakeRecorder)
    app = FastAPI()
    app.include_router(logs_module.router, prefix="/logs")

    response = TestClient(app).get(
        "/logs/conversations",
        params={"conversation_id": "conv-1", "created_from": "not-a-date"},
    )

    assert response.status_code == 422


def test_conversation_jsonl_handler_is_utf8_rotating_and_not_duplicated(tmp_path, monkeypatch):
    from dataworks_agent import main as main_module

    conversation_logger = logging.getLogger("dataworks_agent.conversation")
    for handler in list(conversation_logger.handlers):
        if getattr(handler, "_conversation_jsonl_handler", False):
            conversation_logger.removeHandler(handler)
            handler.close()

    monkeypatch.setattr(
        type(main_module.settings),
        "log_dir",
        property(lambda _settings: str(tmp_path)),
    )
    main_module._setup_logging()
    main_module._setup_logging()

    root_handlers = logging.getLogger().handlers
    assert (
        sum(bool(getattr(handler, "_agent_console_handler", False)) for handler in root_handlers)
        == 1
    )
    assert (
        sum(bool(getattr(handler, "_agent_file_handler", False)) for handler in root_handlers) == 1
    )

    handlers = [
        handler
        for handler in conversation_logger.handlers
        if getattr(handler, "_conversation_jsonl_handler", False)
    ]
    try:
        assert len(handlers) == 1
        handler = handlers[0]
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 5
        assert handler.encoding.lower().replace("-", "") == "utf8"
        assert conversation_logger.propagate is False

        conversation_logger.info(
            "conversation_event",
            extra={
                "conversation_event": {
                    "event": "turn_received",
                    "message": "你好",
                }
            },
        )
        handler.flush()
        lines = (
            (Path(tmp_path) / "conversation-events.jsonl").read_text(encoding="utf-8").splitlines()
        )
        assert json.loads(lines[-1]) == {"event": "turn_received", "message": "你好"}
    finally:
        for handler in handlers:
            conversation_logger.removeHandler(handler)
            handler.close()

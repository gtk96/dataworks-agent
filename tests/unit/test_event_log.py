"""Event_Log unit tests - append/query/Last-Event-ID/masking/Run/Checkpoint."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dataworks_agent.db.database import Base
from dataworks_agent.eventlog import EventLog
from dataworks_agent.eventlog import masking as masking_mod
from dataworks_agent.eventlog import store as store_mod


@pytest.fixture
def event_log(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(store_mod, "SessionLocal", session_factory)
    yield EventLog()
    engine.dispose()


class TestAppendAndQuery:
    def test_append_assigns_monotonic_seq(self, event_log):
        run = event_log.create_run("sess-1")
        r1 = event_log.append(run_id=run, session_id="sess-1", event_type="intent")
        r2 = event_log.append(run_id=run, session_id="sess-1", event_type="step")
        assert r2.seq == r1.seq + 1

    def test_events_by_session_ordered(self, event_log):
        run = event_log.create_run("sess-1")
        for i in range(5):
            event_log.append(run_id=run, session_id="sess-1", event_type=f"e{i}")
        events = event_log.events_by_session("sess-1")
        assert [e.event_type for e in events] == ["e0", "e1", "e2", "e3", "e4"]
        assert [e.seq for e in events] == sorted(e.seq for e in events)

    def test_events_across_runs_same_session_ordered(self, event_log):
        run_a = event_log.create_run("sess-x")
        run_b = event_log.create_run("sess-x")
        event_log.append(run_id=run_a, session_id="sess-x", event_type="a1")
        event_log.append(run_id=run_b, session_id="sess-x", event_type="b1")
        event_log.append(run_id=run_a, session_id="sess-x", event_type="a2")
        events = event_log.events_by_session("sess-x")
        assert [e.event_type for e in events] == ["a1", "b1", "a2"]

    def test_session_isolation(self, event_log):
        run1 = event_log.create_run("s1")
        run2 = event_log.create_run("s2")
        event_log.append(run_id=run1, session_id="s1", event_type="x")
        event_log.append(run_id=run2, session_id="s2", event_type="y")
        assert [e.event_type for e in event_log.events_by_session("s1")] == ["x"]
        assert [e.event_type for e in event_log.events_by_session("s2")] == ["y"]


class TestLastEventId:
    def test_events_since(self, event_log):
        run = event_log.create_run("sess-1")
        recs = [
            event_log.append(run_id=run, session_id="sess-1", event_type=f"e{i}") for i in range(4)
        ]
        after = recs[1].seq
        tail = event_log.events_since(run, after_seq=after)
        assert [e.event_type for e in tail] == ["e2", "e3"]

    def test_events_since_zero_returns_all(self, event_log):
        run = event_log.create_run("sess-1")
        event_log.append(run_id=run, session_id="sess-1", event_type="e0")
        event_log.append(run_id=run, session_id="sess-1", event_type="e1")
        assert len(event_log.events_since(run, after_seq=0)) == 2

    def test_events_since_scoped_to_run(self, event_log):
        run_a = event_log.create_run("s")
        run_b = event_log.create_run("s")
        event_log.append(run_id=run_a, session_id="s", event_type="a")
        event_log.append(run_id=run_b, session_id="s", event_type="b")
        assert [e.event_type for e in event_log.events_since(run_b, 0)] == ["b"]


class TestMasking:
    def test_payload_persisted_and_parsed(self, event_log):
        run = event_log.create_run("sess-1")
        rec = event_log.append(
            run_id=run,
            session_id="sess-1",
            event_type="tool_call",
            payload={"op": "create_node", "count": 3},
        )
        assert rec.payload == {"op": "create_node", "count": 3}
        reloaded = event_log.events_by_session("sess-1")[0]
        assert reloaded.payload == {"op": "create_node", "count": 3}

    def test_sensitive_key_redacted(self, event_log):
        run = event_log.create_run("sess-1")
        rec = event_log.append(
            run_id=run,
            session_id="sess-1",
            event_type="llm_call",
            payload={"api_key": "sk-super-secret-value", "model": "m"},
        )
        assert rec.payload["api_key"] == "***REDACTED***"
        assert rec.payload["model"] == "m"

    def test_known_secret_value_redacted_anywhere(self, event_log, monkeypatch):
        monkeypatch.setattr(masking_mod.settings, "aliyun_access_key_secret", "TOPSECRETAKVALUE123")
        run = event_log.create_run("sess-1")
        rec = event_log.append(
            run_id=run,
            session_id="sess-1",
            event_type="error",
            payload={"msg": "failed with key TOPSECRETAKVALUE123 in header"},
        )
        assert "TOPSECRETAKVALUE123" not in rec.payload["msg"]
        assert "***REDACTED***" in rec.payload["msg"]

    def test_nested_masking(self, event_log):
        run = event_log.create_run("sess-1")
        rec = event_log.append(
            run_id=run,
            session_id="sess-1",
            event_type="x",
            payload={"outer": {"password": "p@ss", "ok": 1}, "list": [{"token": "t"}]},
        )
        assert rec.payload["outer"]["password"] == "***REDACTED***"
        assert rec.payload["outer"]["ok"] == 1
        assert rec.payload["list"][0]["token"] == "***REDACTED***"


class TestRunLifecycle:
    def test_create_and_get_run(self, event_log):
        run = event_log.create_run(
            "sess-1", channel="web", actor_team="team_a", actor_org_code="org1"
        )
        row = event_log.get_run(run)
        assert row.session_id == "sess-1"
        assert row.channel == "web"
        assert row.actor_team == "team_a"
        assert row.status == "submitted"

    def test_update_run_accumulates_cost(self, event_log):
        run = event_log.create_run("sess-1")
        event_log.update_run(run, status="working", add_tokens=100, add_ms=500)
        event_log.update_run(run, add_tokens=50, add_ms=250)
        row = event_log.get_run(run)
        assert row.status == "working"
        assert row.cost_tokens == 150  # regression test
        assert row.cost_ms == 750

    def test_update_missing_run_noop(self, event_log):
        event_log.update_run("nonexistent", status="x")


class TestCheckpoint:
    def test_save_and_latest(self, event_log):
        run = event_log.create_run("sess-1")
        cp1 = event_log.save_checkpoint(run, step_seq=1, state={"phase": "a"})
        cp2 = event_log.save_checkpoint(run, step_seq=2, state={"phase": "b"}, parent_id=cp1)
        latest = event_log.latest_checkpoint(run)
        assert latest.id == cp2
        assert latest.step_seq == 2
        assert latest.parent_id == cp1

    def test_latest_none_when_empty(self, event_log):
        run = event_log.create_run("sess-1")
        assert event_log.latest_checkpoint(run) is None

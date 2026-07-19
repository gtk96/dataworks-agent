"""Event_Log 事实源存储服务（Requirement 9, 24, 29）。

以 session_id 关联记录事件，支持：
- 按 session_id 追加与有序查询（按全局单调 seq）；
- 按 run_id + after_seq 增量查询，支撑 SSE 的 Last-Event-ID 断线续传；
- Run 生命周期与成本累计；
- Checkpoint 保存 / 读取。

写入前经 masking.mask_payload 脱敏 AK/SK 与 LLM_API_Key。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import CheckpointModel, EventModel, RunModel
from dataworks_agent.eventlog.masking import mask_payload

_EVENT_SEQ_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class EventRecord:
    """事件的领域视图（payload 已解析、已脱敏）。"""

    event_id: str
    run_id: str
    session_id: str
    event_type: str
    seq: int
    span_id: str = ""
    parent_span_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    cost_tokens: int = 0
    cost_ms: int = 0
    created_at: str = ""


def _to_record(row: EventModel) -> EventRecord:
    try:
        payload = json.loads(row.payload_json) if row.payload_json else {}
    except json.JSONDecodeError:
        payload = {"_raw": row.payload_json}
    return EventRecord(
        event_id=row.event_id,
        run_id=row.run_id,
        session_id=row.session_id,
        event_type=row.event_type,
        seq=row.seq,
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
        payload=payload,
        cost_tokens=row.cost_tokens,
        cost_ms=row.cost_ms,
        created_at=row.created_at,
    )


class EventLog:
    """Event_Log 事实源门面。

    session_factory 可注入以便测试；默认使用模块级 SessionLocal（可被
    monkeypatch 替换为临时库工厂）。
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory

    def _session(self):
        factory = self._session_factory or SessionLocal
        return factory()

    # ── Run 生命周期 ──

    def create_run(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        channel: str = "",
        actor_user_id: str = "",
        actor_team: str = "",
        actor_org_code: str = "",
        created_by_ip: str = "",
        status: str = "submitted",
    ) -> str:
        """创建一次 Run，返回 run_id。"""
        run_id = run_id or f"run_{uuid.uuid4().hex}"
        now = _utc_now()
        with self._session() as db:
            db.add(
                RunModel(
                    run_id=run_id,
                    session_id=session_id,
                    status=status,
                    channel=channel,
                    actor_user_id=actor_user_id,
                    actor_team=actor_team,
                    actor_org_code=actor_org_code,
                    created_by_ip=created_by_ip,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
        return run_id

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        add_tokens: int = 0,
        add_ms: int = 0,
    ) -> None:
        """更新 Run 状态并累计成本。"""
        with self._session() as db:
            run = db.get(RunModel, run_id)
            if run is None:
                return
            if status is not None:
                run.status = status
            run.cost_tokens += add_tokens
            run.cost_ms += add_ms
            run.updated_at = _utc_now()
            db.commit()

    def get_run(self, run_id: str) -> RunModel | None:
        with self._session() as db:
            return db.get(RunModel, run_id)

    # ── 事件追加与查询 ──

    def append(
        self,
        *,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: Any = None,
        span_id: str = "",
        parent_span_id: str = "",
        cost_tokens: int = 0,
        cost_ms: int = 0,
    ) -> EventRecord:
        """追加一条事件（payload 脱敏后写入），分配全局单调 seq。"""
        masked = mask_payload(payload if payload is not None else {})
        event_id = f"evt_{uuid.uuid4().hex}"
        with _EVENT_SEQ_LOCK, self._session() as db:
            max_seq = db.query(func.max(EventModel.seq)).scalar() or 0
            seq = max_seq + 1
            row = EventModel(
                event_id=event_id,
                run_id=run_id,
                session_id=session_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                event_type=event_type,
                payload_json=json.dumps(masked, ensure_ascii=False),
                cost_tokens=cost_tokens,
                cost_ms=cost_ms,
                seq=seq,
                created_at=_utc_now(),
            )
            db.add(row)
            db.commit()
            return _to_record(row)

    def events_by_session(self, session_id: str) -> list[EventRecord]:
        """按发生顺序（全局 seq 升序）返回某会话的完整事件序列。"""
        with self._session() as db:
            rows = (
                db.query(EventModel)
                .filter(EventModel.session_id == session_id)
                .order_by(EventModel.seq.asc())
                .all()
            )
            return [_to_record(r) for r in rows]

    def events_since(self, run_id: str, after_seq: int = 0) -> list[EventRecord]:
        """返回某 Run 中 seq > after_seq 的事件（Last-Event-ID 续传）。"""
        with self._session() as db:
            rows = (
                db.query(EventModel)
                .filter(EventModel.run_id == run_id, EventModel.seq > after_seq)
                .order_by(EventModel.seq.asc())
                .all()
            )
            return [_to_record(r) for r in rows]

    # ── Checkpoint ──

    def save_checkpoint(
        self,
        run_id: str,
        *,
        step_seq: int,
        state: Any,
        parent_id: int = 0,
    ) -> int:
        """保存一个可恢复快照，返回 checkpoint id。"""
        with self._session() as db:
            row = CheckpointModel(
                run_id=run_id,
                step_seq=step_seq,
                state_json=json.dumps(mask_payload(state), ensure_ascii=False),
                parent_id=parent_id,
                created_at=_utc_now(),
            )
            db.add(row)
            db.commit()
            return row.id

    def latest_checkpoint(self, run_id: str) -> CheckpointModel | None:
        """返回某 Run 最近的 checkpoint（按 step_seq 再按 id 取最大）。"""
        with self._session() as db:
            return (
                db.query(CheckpointModel)
                .filter(CheckpointModel.run_id == run_id)
                .order_by(CheckpointModel.step_seq.desc(), CheckpointModel.id.desc())
                .first()
            )

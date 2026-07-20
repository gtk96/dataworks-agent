"""Persisted, correlated events for each conversation turn."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from dataworks_agent.eventlog.masking import mask_payload
from dataworks_agent.eventlog.store import EventLog

logger = logging.getLogger("dataworks_agent.conversation")

_SENSITIVE_CONVERSATION_KEY_HINTS = (
    "authorization",
    "cookie",
    "sql",
    "query",
    "prompt",
    "input_text",
    "message",
    "email",
    "phone",
)
_REDACTED = "***REDACTED***"


def _mask_conversation_fields(value: Any, *, key: str = "") -> Any:
    if key and any(hint in key.lower() for hint in _SENSITIVE_CONVERSATION_KEY_HINTS):
        return _REDACTED
    if isinstance(value, dict):
        return {
            item_key: _mask_conversation_fields(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_conversation_fields(item) for item in value]
    return value


@dataclass(frozen=True)
class TurnTrace:
    conversation_id: str
    request_id: str
    turn_id: str
    started_at: float


class ConversationEventRecorder:
    """Record one ordered, masked event stream per conversation turn."""

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._event_log = event_log or EventLog()

    def start_turn(
        self,
        conversation_id: str,
        *,
        request_id: str | None = None,
        input_text: str = "",
    ) -> TurnTrace:
        trace = TurnTrace(
            conversation_id=conversation_id,
            request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
            turn_id=f"turn_{uuid.uuid4().hex[:12]}",
            started_at=time.monotonic(),
        )
        self._event_log.create_run(
            conversation_id,
            run_id=trace.turn_id,
            channel="web",
            status="running",
        )
        self.emit(trace, "turn_received", input_length=len(input_text))
        return trace

    def emit(self, trace: TurnTrace, event: str, **payload: Any) -> None:
        default_level = "ERROR" if event == "turn_failed" else "INFO"
        level = str(payload.pop("level", default_level)).upper()
        body = _mask_conversation_fields(
            mask_payload(
                {
                    "event": event,
                    "level": level,
                    "request_id": trace.request_id,
                    "conversation_id": trace.conversation_id,
                    "turn_id": trace.turn_id,
                    **payload,
                }
            )
        )
        stored = self._event_log.append(
            run_id=trace.turn_id,
            session_id=trace.conversation_id,
            event_type=event,
            payload=body,
        )
        logger.log(
            getattr(logging, level, logging.INFO),
            "conversation_event",
            extra={
                "conversation_event": {
                    "seq": stored.seq,
                    "created_at": stored.created_at,
                    **body,
                }
            },
        )

    def finish(self, trace: TurnTrace, *, success: bool, **payload: Any) -> None:
        payload.setdefault("level", "INFO" if success else "ERROR")
        self.emit(
            trace,
            "response_sent",
            outcome="success" if success else "failed",
            duration_ms=int((time.monotonic() - trace.started_at) * 1000),
            **payload,
        )
        self._event_log.update_run(
            trace.turn_id,
            status="completed" if success else "failed",
        )

    def events(self, *, conversation_id: str) -> list[dict[str, Any]]:
        return [
            {"seq": item.seq, "created_at": item.created_at, **item.payload}
            for item in self._event_log.events_by_session(conversation_id)
        ]

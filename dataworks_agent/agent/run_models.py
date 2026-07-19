"""Models shared by the bounded conversational Agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dataworks_agent.agent.interaction import InteractionAnswer


@dataclass(frozen=True)
class AgentRunRequest:
    conversation_id: str
    message: str
    interaction_answer: InteractionAnswer | dict[str, Any] | None = None
    request_type: str | None = None
    context_updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResponse:
    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class RunEvent:
    type: str
    run_id: str
    sequence: int
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "data": dict(self.data),
        }


def new_run_id() -> str:
    return f"run_{uuid4().hex}"

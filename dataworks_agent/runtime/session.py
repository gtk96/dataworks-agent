"""Runtime 协议对象 — Session、Run、Step、Event、Artifact、Checkpoint。

实现 Requirement 29：Runtime 协议对象与生命周期操作（框架无关）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    """Run 状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class StepStatus(StrEnum):
    """Step 状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventType(StrEnum):
    """Event 类型。"""

    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    STEP_FAIL = "step_fail"
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    HANDOFF = "handoff"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    ERROR = "error"
    ARTIFACT = "artifact"


@dataclass
class Session:
    """会话 — 长期上下文边界。

    复用 modeling_tasks / pipeline_tasks 作为载体。
    """

    session_id: str
    task_id: str
    task_type: str  # modeling / pipeline
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class Run:
    """运行 — 一次执行边界。

    承载超时、取消、成本、审批与最终结果。
    """

    run_id: str
    session_id: str
    status: RunStatus = RunStatus.PENDING
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    actor: str = ""
    started_at: str = ""
    completed_at: str = ""
    timeout_seconds: int = 3600
    cost_tokens: int = 0
    cost_ms: int = 0

    def __post_init__(self):
        if not self.run_id:
            self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        if not self.started_at:
            self.started_at = datetime.now(UTC).isoformat()


@dataclass
class Step:
    """步骤 — 可观测执行单元。

    由 task_step_logs / pipeline_step_logs 承载。
    """

    step_id: str
    run_id: str
    step_name: str
    status: StepStatus = StepStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    span_id: str = ""
    parent_span_id: str = ""

    def __post_init__(self):
        if not self.step_id:
            self.step_id = f"step_{uuid.uuid4().hex[:12]}"
        if not self.span_id:
            self.span_id = f"span_{uuid.uuid4().hex[:8]}"


@dataclass
class Event:
    """事件 — 进展增量。

    由 Event_Log + SSE 提供。
    """

    event_id: str
    run_id: str
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    span_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"evt_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class Artifact:
    """产物 — 可引用、可追溯到 Run。

    由 artifacts 表承载。
    """

    artifact_id: str
    run_id: str
    artifact_type: str  # ddl / dml / report / config
    name: str
    content: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.artifact_id:
            self.artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class Checkpoint:
    """检查点 — 可恢复的执行快照。

    用于中断恢复、错误回滚与重放。
    """

    checkpoint_id: str
    run_id: str
    step_index: int
    state: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.checkpoint_id:
            self.checkpoint_id = f"ckpt_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

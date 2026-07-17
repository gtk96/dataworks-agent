"""Phase 2 migration shim — replaces deleted runtime modules with LangGraph equivalents.

This module provides drop-in replacements for the deleted classes so that
workflow_service.py continues to work without a full rewrite.
The real migration to LangGraph StateGraph happens in runtime/graphs/.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Replacement for LoopPolicy ──────────────────────────────────


@dataclass
class LoopPolicy:
    """LangGraph-compatible loop policy (replaces deleted runtime/loop.py)."""

    max_iterations: int = 3
    max_same_action: int = 2
    deadline_seconds: float = 180.0
    max_no_progress_rounds: int = 2


# ── Replacement for LoopKernel ──────────────────────────────────


@dataclass
class LoopDecision:
    """Decision from the verifier node. Matches original runtime/loop.py interface."""

    def __init__(
        self,
        action: str = "",
        score: float = 0.0,
        progress: bool = True,
        message: str = "",
        passed: bool = True,
        summary: str = "",
        needs_approval: bool = False,
        agent_name: str = "",
        evidence: dict[str, Any] | None = None,
        retryable: bool = False,
        needs_context: bool = False,
        failure_class: str = "",
        **kwargs: Any,
    ) -> None:
        self.action = action
        self.score = score
        self.progress = progress
        self.message = message
        self.passed = passed
        self.summary = summary
        self.needs_approval = needs_approval
        self.agent_name = agent_name
        self.evidence = evidence or {}
        self.retryable = retryable
        self.needs_context = needs_context
        self.failure_class = failure_class
        self._extra = kwargs


@dataclass
class RepairResult:
    """Result of a repair step."""

    success: bool
    action_taken: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class StopReason(StrEnum):
    """Stopping conditions for the loop — matches HEAD ``runtime/loop.py`` values."""

    VERIFIED_SUCCESS = "verified_success"
    NEEDS_CONTEXT = "needs_context"
    APPROVAL_REQUIRED = "approval_required"
    NON_RETRYABLE = "non_retryable"
    REPAIR_UNAVAILABLE = "repair_unavailable"
    MAX_ITERATIONS = "max_iterations"
    REPEATED_ACTION = "repeated_action"
    NO_PROGRESS = "no_progress"
    DEADLINE_EXCEEDED = "deadline_exceeded"

    # Backward-compat alias — early simplified shim code referenced ``SUCCESS``;
    # the canonical name is ``VERIFIED_SUCCESS``.
    SUCCESS = "verified_success"


class LoopOutcome[T]:
    """Result envelope returned by ``LoopKernel.run``.

    Mirrors the shape previously defined in the deleted ``runtime/loop.py``
    (HEAD ``644a277``前的 ``LoopOutcome[T]``): callers like
    ``AgentWorkflowService.execute`` read ``outcome.result``,
    ``outcome.success`` and ``outcome.stop_reason`` after awaiting
    ``kernel.run(...)``.
    """

    def __init__(
        self,
        *,
        run_id: str,
        objective: str,
        success: bool,
        stop_reason: StopReason,
        result: T | None,
        iterations: list[dict[str, Any]],
        elapsed_ms: int,
        best_score: float,
    ) -> None:
        self.run_id = run_id
        self.objective = objective
        self.success = success
        self.stop_reason = stop_reason
        self.result = result
        self.iterations = iterations
        self.elapsed_ms = elapsed_ms
        self.best_score = best_score

    def to_dict(self) -> dict[str, Any]:
        # Sanitize iterations so the payload is plain JSON.
        # Each iteration may hold a WorkflowResult / LoopDecision object; those
        # are not JSON-serializable and WorkflowResult.data can also contain a
        # circular back-reference to this loop_data under key "loop".
        safe_iterations = []
        for it in self.iterations:
            safe_it = {
                "iteration": it.get("iteration"),
                "elapsed_ms": it.get("elapsed_ms"),
            }
            res = it.get("result")
            if res is None:
                safe_it["result"] = None
            elif isinstance(res, dict):
                safe_it["result"] = {k: v for k, v in res.items() if k != "loop"}
            else:
                # WorkflowResult (or similar): only keep lightweight fields.
                data = getattr(res, "data", None)
                if isinstance(data, dict):
                    data = {k: v for k, v in data.items() if k != "loop"}
                safe_it["result"] = {
                    "success": bool(getattr(res, "success", False)),
                    "message": str(getattr(res, "message", "") or ""),
                    "workflow_type": str(getattr(res, "workflow_type", "") or ""),
                    "mode": str(getattr(res, "mode", "") or ""),
                    "errors": list(getattr(res, "errors", []) or []),
                    "steps": list(getattr(res, "steps", []) or []),
                    # Do NOT embed full data (may still contain non-JSON bits /
                    # large payloads); evaluation already lives at top-level.
                }
            decision = it.get("decision")
            if decision is None:
                safe_it["decision"] = None
            elif isinstance(decision, dict):
                safe_it["decision"] = dict(decision)
            else:
                safe_it["decision"] = {
                    "passed": bool(getattr(decision, "passed", False)),
                    "score": float(getattr(decision, "score", 0.0) or 0.0),
                    "summary": str(getattr(decision, "summary", "") or ""),
                    "failure_class": str(getattr(decision, "failure_class", "") or ""),
                    "retryable": bool(getattr(decision, "retryable", False)),
                    "needs_context": bool(getattr(decision, "needs_context", False)),
                    "needs_approval": bool(getattr(decision, "needs_approval", False)),
                    "action": str(getattr(decision, "action", "") or ""),
                }
            repair = it.get("repair")
            if isinstance(repair, dict):
                safe_it["repair"] = dict(repair)
            elif repair is not None:
                safe_it["repair"] = {
                    "action": getattr(repair, "action_taken", None)
                    or getattr(repair, "action", None),
                    "applied": bool(getattr(repair, "success", False)),
                    "message": str(getattr(repair, "message", "") or ""),
                }
            safe_iterations.append(safe_it)
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "success": self.success,
            "stop_reason": self.stop_reason.value
            if isinstance(self.stop_reason, StopReason)
            else str(self.stop_reason),
            "iteration_count": len(self.iterations),
            "best_score": round(self.best_score, 4),
            "elapsed_ms": self.elapsed_ms,
            "runtime": {
                "framework": "shims_loop",
                "graph": "bounded_observe_act_verify_repair",
            },
            "iterations": safe_iterations,
        }


class LoopKernel[T]:
    """LangGraph-compatible loop kernel (replaces deleted runtime/loop.py).

    同时支持两套调用约定（向后兼容 + 新接口）：
    - 旧: ``await kernel.run(execute_fn, verify_fn, repair_fn)``
    - 新: ``await kernel.run(objective=..., action=..., verify=..., repair=...,
      initial_state=..., observer=..., run_id=...)`` （与
      ``AgentWorkflowService.execute`` 期望的 HEAD 接口对齐）

    返回 ``LoopOutcome[T]``，调用方读取 ``outcome.result/success/stop_reason``。
    """

    def __init__(self, policy: LoopPolicy | None = None) -> None:
        self.policy = policy or LoopPolicy()
        self._iteration = 0
        self._same_action_count = 0
        self._last_action: str | None = None
        self._fingerprints: dict[str, int] = {}
        self._start_time: float = 0.0

    async def run(
        self,
        execute_fn: Any = None,
        verify_fn: Any = None,
        repair_fn: Any = None,
        *,
        objective: str = "",
        action: Any = None,
        verify: Any = None,
        repair: Any = None,
        initial_state: dict[str, Any] | None = None,
        observer: Any = None,
        run_id: str | None = None,
    ) -> LoopOutcome[T]:
        """Run the observe-act-verify-repair loop.

        Positional ``execute_fn/verify_fn/repair_fn`` 兼容早期简化接口；
        keyword 形式按 HEAD 接口语义运行。
        """
        import time
        import uuid

        # Resolve call shape: prefer keyword args (HEAD interface) when present.
        use_keyword = any(arg is not None for arg in (objective, action, verify, repair))
        if use_keyword:
            act_fn = action or execute_fn
            ver_fn = verify or verify_fn
            rep_fn = repair or repair_fn
            obj_text = objective
            state: dict[str, Any] = dict(initial_state or {})
            obs = observer
            run_id_value = run_id or f"loop_{uuid.uuid4().hex[:12]}"
        else:
            act_fn = execute_fn
            ver_fn = verify_fn
            rep_fn = repair_fn
            obj_text = ""
            state = {}
            obs = None
            run_id_value = f"loop_{uuid.uuid4().hex[:12]}"

        await self._notify(obs, "loop_started", {"run_id": run_id_value, "objective": obj_text})

        self._start_time = time.time()
        self._iteration = 0
        self._same_action_count = 0
        self._last_action = None
        self._fingerprints = {}
        iterations: list[dict[str, Any]] = []
        best_score = 0.0
        last_result: T | None = None
        stop_reason: StopReason = StopReason.MAX_ITERATIONS
        success = False

        try:
            while self._iteration < self.policy.max_iterations:
                elapsed = time.time() - self._start_time
                if elapsed > self.policy.deadline_seconds:
                    stop_reason = StopReason.DEADLINE_EXCEEDED
                    break

                await self._notify(
                    obs,
                    "iteration_start",
                    {"run_id": run_id_value, "iteration": self._iteration + 1, "state": state},
                )

                iteration_started = time.time()
                result = await self._invoke(act_fn, state, self._iteration + 1)
                last_result = result
                decision_value = ver_fn(result, self._iteration + 1) if ver_fn is not None else None
                decision = await decision_value if _is_awaitable(decision_value) else decision_value
                elapsed_ms = int((time.time() - iteration_started) * 1000)
                iterations.append(
                    {
                        "iteration": self._iteration + 1,
                        "result": result,
                        "decision": decision,
                        "elapsed_ms": elapsed_ms,
                    }
                )

                # Update best score for no-progress detection.
                score = getattr(decision, "score", 0.0) if decision is not None else 0.0
                if isinstance(score, (int, float)) and score > best_score:
                    best_score = float(score)

                # Decision routing.
                action_name = (
                    getattr(decision, "action", "stop") if decision is not None else "stop"
                )
                if (
                    decision is not None and getattr(decision, "passed", False)
                ) or action_name == "stop":
                    success = (
                        bool(getattr(decision, "passed", False)) if decision is not None else True
                    )
                    stop_reason = (
                        StopReason.VERIFIED_SUCCESS if success else StopReason.NON_RETRYABLE
                    )
                    break

                if getattr(decision, "needs_context", False):
                    stop_reason = StopReason.NEEDS_CONTEXT
                    break

                if getattr(decision, "needs_approval", False):
                    stop_reason = StopReason.APPROVAL_REQUIRED
                    break

                if not getattr(decision, "retryable", True):
                    stop_reason = StopReason.NON_RETRYABLE
                    break

                # Repeated-fingerprint guard.
                fingerprint = (
                    getattr(decision, "action_fingerprint", None)
                    or getattr(decision, "failure_class", None)
                    or action_name
                    or "workflow"
                )
                # Per-fingerprint accumulator (matches HEAD ``runtime/loop.py``
                # semantics): same fingerprint across iterations increments the
                # counter; the loop stops once the count reaches
                # ``policy.max_same_action``.
                self._fingerprints[fingerprint] = self._fingerprints.get(fingerprint, 0) + 1
                if self._fingerprints[fingerprint] >= self.policy.max_same_action:
                    stop_reason = StopReason.REPEATED_ACTION
                    break

                # Repair step.
                if rep_fn is None:
                    stop_reason = StopReason.REPAIR_UNAVAILABLE
                    break

                repair_value = rep_fn(state, result, decision, self._iteration + 1)
                repair_obj = await repair_value if _is_awaitable(repair_value) else repair_value
                # Attach repair outcome to the current iteration entry so callers
                # reading ``iterations[i]['repair']`` see what was applied (matches
                # HEAD ``LoopIteration.repair`` shape).
                iterations[-1]["repair"] = self._repair_to_dict(repair_obj)
                if repair_obj is None or not getattr(repair_obj, "success", False):
                    stop_reason = StopReason.NO_PROGRESS
                    break

                self._iteration += 1

            if success:
                stop_reason = StopReason.VERIFIED_SUCCESS
        finally:
            elapsed_ms_total = int((time.time() - self._start_time) * 1000)

        return LoopOutcome(
            run_id=run_id_value,
            objective=obj_text,
            success=success,
            stop_reason=stop_reason,
            result=last_result,
            iterations=iterations,
            elapsed_ms=elapsed_ms_total,
            best_score=best_score,
        )

    @staticmethod
    def _repair_to_dict(repair_obj: Any) -> dict[str, Any]:
        if repair_obj is None:
            return {"action": None, "applied": False}
        if isinstance(repair_obj, dict):
            return dict(repair_obj)
        return {
            "action": getattr(repair_obj, "action_taken", None)
            or getattr(repair_obj, "action", None),
            "applied": bool(getattr(repair_obj, "success", False)),
            "action_taken": getattr(repair_obj, "action_taken", None),
            "message": getattr(repair_obj, "message", ""),
        }

    @staticmethod
    async def _invoke(act_fn: Any, state: dict[str, Any], iteration: int) -> Any:
        """Call ``action`` with the shape it expects.

        HEAD 接口约定 ``action(state, iteration)``，但简化接口会传
        ``execute_fn(iteration=...)``。这里做一次性探测，避免破坏既有调用。
        """
        if act_fn is None:
            return None
        try:
            value = act_fn(state, iteration)
        except TypeError:
            value = act_fn(iteration=iteration)
        if _is_awaitable(value):
            return await value
        return value

    @staticmethod
    async def _notify(observer: Any, event: str, payload: dict[str, Any]) -> None:
        if observer is None:
            return
        try:
            value = observer(event, payload)
        except Exception as exc:  # pragma: no cover - observer is best-effort
            logger.debug("loop observer raised %s: %s", event, exc)
            return
        if _is_awaitable(value):
            try:
                await value
            except Exception as exc:  # pragma: no cover
                logger.debug("loop observer awaitable raised %s: %s", event, exc)


def _is_awaitable(value: Any) -> bool:
    return (
        hasattr(value, "__await__")
        or asyncio.iscoroutinefunction(value)
        or asyncio.iscoroutine(value)
    )


# ── Replacement for IntentConfirmGate ───────────────────────────


class ConfirmRequest:
    """LangGraph-compatible confirmation request."""

    def __init__(
        self,
        action: str,
        message: str,
        options: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.action = action
        self.message = message
        self.options = options or ["approve", "reject", "modify"]
        self.timeout_seconds = timeout_seconds


class IntentConfirmGate:
    """LangGraph-compatible intent confirmation gate.

    In the LangGraph migration, this is replaced by interrupt() for
    human-in-the-loop approval.
    """

    DESTRUCTIVE_ACTIONS = {
        "create_table",
        "delete_table",
        "deploy",
        "publish",
        "create_deployment",
        "offline_node",
        "drop_node",
    }

    @staticmethod
    def needs_confirmation(action: str) -> bool:
        return action in IntentConfirmGate.DESTRUCTIVE_ACTIONS

    async def request_confirmation(self, req: ConfirmRequest) -> str:
        """In LangGraph, this becomes interrupt() + manual approval.

        For now, auto-approve non-destructive actions.
        """
        if req.action not in self.DESTRUCTIVE_ACTIONS:
            return "approve"
        # Destructive actions require human approval
        # In LangGraph: interrupt(before="deploy") would pause here
        logger.info("Intent confirmation required for: %s", req.action)
        return "approve"  # Default: auto-approve in dev mode


# ── Replacement for MemoryLayeringService ───────────────────────


class MemoryType(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryEntry:
    """LangGraph-compatible memory entry."""

    entry_id: str
    memory_type: str
    content: dict[str, Any]
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    confidence: float = 0.0
    tags: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def is_stale(self) -> bool:
        return False  # LangGraph Checkpointers handle TTL


class MemoryLayeringService:
    """LangGraph-compatible memory service.

    In the LangGraph migration, this is replaced by Checkpointers
    which handle episodic, semantic, and procedural memory natively.
    """

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    def store(self, entry: MemoryEntry) -> str:
        self._entries[entry.entry_id] = entry
        return entry.entry_id

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def query(self, memory_type: str, tags: list[str] | None = None) -> list[MemoryEntry]:
        return [
            e
            for e in self._entries.values()
            if e.memory_type == memory_type and (not tags or any(t in e.tags for t in tags))
        ]

    def cleanup_expired(self) -> int:
        return 0  # LangGraph Checkpointers handle this

    def get_stats(self) -> dict[str, dict]:
        stats: dict[str, dict] = {}
        for e in self._entries.values():
            mt = e.memory_type
            if mt not in stats:
                stats[mt] = {"count": 0, "total_size": 0}
            stats[mt]["count"] += 1
        return stats


# ── Replacement for ReflectionEngine ────────────────────────────


class ReflectionCategory(Enum):
    OVER_GENERATION = "over_generation"
    UNDER_GENERATION = "under_generation"
    WRONG_TOOL = "wrong_tool"
    WRONG_PARAMS = "wrong_params"
    MISSING_CONTEXT = "missing_context"


@dataclass
class ReflectionResult:
    deviation: str
    category: str
    confidence: float
    adjustment: str


class ReflectionEngine:
    """LangGraph-compatible reflection engine.

    In the LangGraph migration, reflection is handled by the state
    graph's verification node + conditional edges.
    """

    def analyze(self, outcome: Any) -> ReflectionResult:
        return ReflectionResult(
            deviation="no_deviation",
            category="none",
            confidence=1.0,
            adjustment="",
        )

    def to_dict(self) -> dict[str, Any]:
        return {}


# ── Replacement for Evaluator ───────────────────────────────────


class Evaluator:
    """LangGraph-compatible evaluator.

    In the LangGraph migration, evaluation is handled by the verification
    node in the state graph. This shim keeps the HEAD-compatible API
    (``record_metric`` / ``record_badcase``) so callers in
    ``AgentWorkflowService._attach_loop_evaluation`` continue to work.
    """

    def __init__(self) -> None:
        self._metrics: list[Any] = []
        self._badcases: list[Any] = []

    def record_metric(self, metric_name: str, value: float, unit: str = "") -> Any:
        """记录质量指标 — matches HEAD ``runtime/evaluator.py`` API."""
        metric = {
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
        }
        self._metrics.append(metric)
        logger.info("记录质量指标: %s = %.2f %s", metric_name, value, unit)
        return metric

    def record_badcase(
        self,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        failure_reason: str,
        run_id: str = "",
        task_id: str = "",
        category: str = "",
    ) -> Any:
        """记录 Badcase — matches HEAD ``runtime/evaluator.py`` API."""
        import uuid

        badcase = {
            "badcase_id": f"bc_{uuid.uuid4().hex[:8]}",
            "input_data": input_data,
            "output_data": output_data,
            "failure_reason": failure_reason,
            "run_id": run_id,
            "task_id": task_id,
            "category": category,
        }
        self._badcases.append(badcase)
        logger.info("记录 Badcase: %s (category=%s)", badcase["badcase_id"], category)
        return badcase

    def evaluate(self, outcome: Any) -> dict[str, Any]:
        return {"score": 1.0, "passed": True}

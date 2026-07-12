"""Bounded observe-act-verify-repair loop for reliable Agent workflows."""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

T = TypeVar("T")
LoopAction = Callable[[dict[str, Any], int], Awaitable[T]]
LoopVerifier = Callable[[T, int], "LoopDecision | Awaitable[LoopDecision]"]
LoopRepair = Callable[
    [dict[str, Any], T, "LoopDecision", int], "RepairResult | Awaitable[RepairResult]"
]
LoopObserver = Callable[[str, dict[str, Any]], Any]


class StopReason(StrEnum):
    VERIFIED_SUCCESS = "verified_success"
    NEEDS_CONTEXT = "needs_context"
    APPROVAL_REQUIRED = "approval_required"
    NON_RETRYABLE = "non_retryable"
    REPAIR_UNAVAILABLE = "repair_unavailable"
    MAX_ITERATIONS = "max_iterations"
    REPEATED_ACTION = "repeated_action"
    NO_PROGRESS = "no_progress"
    DEADLINE_EXCEEDED = "deadline_exceeded"


@dataclass(frozen=True)
class LoopPolicy:
    """Global stopping policy shared by conversational workflows."""

    max_iterations: int = 3
    max_same_action: int = 2
    max_no_progress_rounds: int = 1
    deadline_seconds: float = 180.0
    min_progress_delta: float = 0.001

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.max_same_action < 1:
            raise ValueError("max_same_action must be >= 1")
        if self.max_no_progress_rounds < 0:
            raise ValueError("max_no_progress_rounds must be >= 0")
        if self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be > 0")


@dataclass(frozen=True)
class LoopDecision:
    """Outcome contract returned by a workflow verifier."""

    passed: bool
    score: float
    summary: str
    failure_class: str = ""
    retryable: bool = False
    needs_context: bool = False
    approval_required: bool = False
    action_fingerprint: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairResult:
    applied: bool
    action: str = ""
    summary: str = ""
    state_updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopIteration[T]:
    iteration: int
    decision: LoopDecision
    repair: RepairResult | None = None
    result: T | None = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "score": round(self.decision.score, 4),
            "passed": self.decision.passed,
            "summary": self.decision.summary,
            "failure_class": self.decision.failure_class,
            "retryable": self.decision.retryable,
            "action_fingerprint": self.decision.action_fingerprint,
            "evidence": self.decision.evidence,
            "repair": (
                {
                    "applied": self.repair.applied,
                    "action": self.repair.action,
                    "summary": self.repair.summary,
                    "state_updates": self.repair.state_updates,
                }
                if self.repair
                else None
            ),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class LoopOutcome[T]:
    run_id: str
    objective: str
    success: bool
    stop_reason: StopReason
    result: T
    iterations: list[LoopIteration[T]]
    elapsed_ms: int
    best_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "success": self.success,
            "stop_reason": self.stop_reason.value,
            "iteration_count": len(self.iterations),
            "best_score": round(self.best_score, 4),
            "elapsed_ms": self.elapsed_ms,
            "iterations": [item.to_dict() for item in self.iterations],
        }


class LoopKernel[T]:
    """Execute a bounded workflow until outcome verification passes or policy stops it."""

    def __init__(self, policy: LoopPolicy | None = None) -> None:
        self.policy = policy or LoopPolicy()

    async def run(
        self,
        *,
        objective: str,
        action: LoopAction[T],
        verify: LoopVerifier[T],
        repair: LoopRepair[T] | None = None,
        initial_state: dict[str, Any] | None = None,
        observer: LoopObserver | None = None,
        run_id: str | None = None,
    ) -> LoopOutcome[T]:
        started = time.monotonic()
        state = dict(initial_state or {})
        loop_run_id = run_id or f"loop_{uuid.uuid4().hex[:12]}"
        iterations: list[LoopIteration[T]] = []
        best_score = -1.0
        no_progress_rounds = 0
        fingerprints: dict[str, int] = {}
        last_result: T | None = None
        stop_reason = StopReason.MAX_ITERATIONS

        for iteration_number in range(1, self.policy.max_iterations + 1):
            elapsed = time.monotonic() - started
            if elapsed >= self.policy.deadline_seconds:
                stop_reason = StopReason.DEADLINE_EXCEEDED
                break

            await self._notify(
                observer,
                "iteration_start",
                {"run_id": loop_run_id, "iteration": iteration_number, "state": state},
            )
            iteration_started = time.monotonic()
            last_result = await action(state, iteration_number)
            decision_value = verify(last_result, iteration_number)
            decision = (
                await decision_value if inspect.isawaitable(decision_value) else decision_value
            )
            item = LoopIteration(
                iteration=iteration_number,
                decision=decision,
                result=last_result,
                elapsed_ms=int((time.monotonic() - iteration_started) * 1000),
            )
            iterations.append(item)
            await self._notify(observer, "iteration_verified", item.to_dict())

            if decision.passed:
                stop_reason = StopReason.VERIFIED_SUCCESS
                break
            if decision.needs_context:
                stop_reason = StopReason.NEEDS_CONTEXT
                break
            if decision.approval_required:
                stop_reason = StopReason.APPROVAL_REQUIRED
                break
            if not decision.retryable:
                stop_reason = StopReason.NON_RETRYABLE
                break

            fingerprint = decision.action_fingerprint or decision.failure_class or "workflow"
            fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1
            if fingerprints[fingerprint] >= self.policy.max_same_action:
                stop_reason = StopReason.REPEATED_ACTION
                break

            if decision.score > best_score + self.policy.min_progress_delta:
                best_score = decision.score
                no_progress_rounds = 0
            else:
                no_progress_rounds += 1
            if no_progress_rounds > self.policy.max_no_progress_rounds:
                stop_reason = StopReason.NO_PROGRESS
                break

            if iteration_number >= self.policy.max_iterations:
                stop_reason = StopReason.MAX_ITERATIONS
                break
            if repair is None:
                stop_reason = StopReason.REPAIR_UNAVAILABLE
                break

            repair_value = repair(state, last_result, decision, iteration_number)
            repair_result = (
                await repair_value if inspect.isawaitable(repair_value) else repair_value
            )
            item.repair = repair_result
            if repair_result.state_updates:
                state.update(repair_result.state_updates)
            await self._notify(
                observer,
                "repair_applied" if repair_result.applied else "repair_skipped",
                {"iteration": iteration_number, **item.to_dict()},
            )
            if not repair_result.applied:
                stop_reason = StopReason.REPAIR_UNAVAILABLE
                break

        if last_result is None:
            raise RuntimeError("loop stopped before the first action completed")

        elapsed_ms = int((time.monotonic() - started) * 1000)
        best = max((item.decision.score for item in iterations), default=0.0)
        outcome = LoopOutcome(
            run_id=loop_run_id,
            objective=objective,
            success=stop_reason == StopReason.VERIFIED_SUCCESS,
            stop_reason=stop_reason,
            result=last_result,
            iterations=iterations,
            elapsed_ms=elapsed_ms,
            best_score=best,
        )
        await self._notify(observer, "loop_stopped", outcome.to_dict())
        return outcome

    @staticmethod
    async def _notify(observer: LoopObserver | None, event: str, payload: dict[str, Any]) -> None:
        if observer is None:
            return
        value = observer(event, payload)
        if inspect.isawaitable(value):
            await value

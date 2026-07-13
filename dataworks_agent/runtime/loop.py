"""LangGraph-backed bounded observe-act-verify-repair runtime."""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypedDict, TypeVar

from langgraph.graph import END, START, StateGraph

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
            "runtime": {
                "framework": "langgraph",
                "graph": "bounded_workflow_loop",
            },
            "iterations": [item.to_dict() for item in self.iterations],
        }


class _LoopState(TypedDict, total=False):
    started: float
    loop_run_id: str
    runtime_state: dict[str, Any]
    iteration: int
    iterations: list[LoopIteration[Any]]
    best_score: float
    no_progress_rounds: int
    fingerprints: dict[str, int]
    last_result: Any
    stop_reason: StopReason


class LoopKernel[T]:
    """Run reliable workflows on LangGraph instead of a project-local loop engine."""

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
        """Compile and execute a bounded LangGraph state machine."""
        started = time.monotonic()
        loop_run_id = run_id or f"loop_{uuid.uuid4().hex[:12]}"

        async def act_and_verify(state: _LoopState) -> dict[str, Any]:
            if time.monotonic() - state["started"] >= self.policy.deadline_seconds:
                return {"stop_reason": StopReason.DEADLINE_EXCEEDED}

            iteration_number = state.get("iteration", 0) + 1
            runtime_state = dict(state.get("runtime_state", {}))
            await self._notify(
                observer,
                "iteration_start",
                {
                    "run_id": state["loop_run_id"],
                    "iteration": iteration_number,
                    "state": runtime_state,
                },
            )

            iteration_started = time.monotonic()
            result = await action(runtime_state, iteration_number)
            decision_value = verify(result, iteration_number)
            decision = (
                await decision_value if inspect.isawaitable(decision_value) else decision_value
            )
            item = LoopIteration(
                iteration=iteration_number,
                decision=decision,
                result=result,
                elapsed_ms=int((time.monotonic() - iteration_started) * 1000),
            )
            iterations = [*state.get("iterations", []), item]
            await self._notify(observer, "iteration_verified", item.to_dict())

            update: dict[str, Any] = {
                "iteration": iteration_number,
                "iterations": iterations,
                "last_result": result,
                "runtime_state": runtime_state,
            }
            if decision.passed:
                update["stop_reason"] = StopReason.VERIFIED_SUCCESS
                return update
            if decision.needs_context:
                update["stop_reason"] = StopReason.NEEDS_CONTEXT
                return update
            if decision.approval_required:
                update["stop_reason"] = StopReason.APPROVAL_REQUIRED
                return update
            if not decision.retryable:
                update["stop_reason"] = StopReason.NON_RETRYABLE
                return update

            fingerprint = decision.action_fingerprint or decision.failure_class or "workflow"
            fingerprints = dict(state.get("fingerprints", {}))
            fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1
            update["fingerprints"] = fingerprints
            if fingerprints[fingerprint] >= self.policy.max_same_action:
                update["stop_reason"] = StopReason.REPEATED_ACTION
                return update

            best_score = state.get("best_score", -1.0)
            no_progress_rounds = state.get("no_progress_rounds", 0)
            if decision.score > best_score + self.policy.min_progress_delta:
                best_score = decision.score
                no_progress_rounds = 0
            else:
                no_progress_rounds += 1
            update["best_score"] = best_score
            update["no_progress_rounds"] = no_progress_rounds
            if no_progress_rounds > self.policy.max_no_progress_rounds:
                update["stop_reason"] = StopReason.NO_PROGRESS
                return update
            if iteration_number >= self.policy.max_iterations:
                update["stop_reason"] = StopReason.MAX_ITERATIONS
                return update
            if repair is None:
                update["stop_reason"] = StopReason.REPAIR_UNAVAILABLE
            return update

        async def apply_repair(state: _LoopState) -> dict[str, Any]:
            result = state["last_result"]
            iterations = list(state["iterations"])
            current = iterations[-1]
            repair_value = repair(
                dict(state.get("runtime_state", {})),
                result,
                current.decision,
                current.iteration,
            ) if repair is not None else RepairResult(False)
            repair_result = (
                await repair_value if inspect.isawaitable(repair_value) else repair_value
            )
            current.repair = repair_result
            runtime_state = dict(state.get("runtime_state", {}))
            runtime_state.update(repair_result.state_updates)
            await self._notify(
                observer,
                "repair_applied" if repair_result.applied else "repair_skipped",
                {"iteration": current.iteration, **current.to_dict()},
            )
            update: dict[str, Any] = {
                "iterations": iterations,
                "runtime_state": runtime_state,
            }
            if not repair_result.applied:
                update["stop_reason"] = StopReason.REPAIR_UNAVAILABLE
            return update

        def after_verify(state: _LoopState) -> str:
            return "end" if state.get("stop_reason") is not None else "repair"

        def after_repair(state: _LoopState) -> str:
            return "end" if state.get("stop_reason") is not None else "act"

        graph_builder = StateGraph(_LoopState)
        graph_builder.add_node("act_and_verify", act_and_verify)
        graph_builder.add_node("repair", apply_repair)
        graph_builder.add_edge(START, "act_and_verify")
        graph_builder.add_conditional_edges(
            "act_and_verify",
            after_verify,
            {"repair": "repair", "end": END},
        )
        graph_builder.add_conditional_edges(
            "repair",
            after_repair,
            {"act": "act_and_verify", "end": END},
        )
        graph = graph_builder.compile()
        final_state = await graph.ainvoke(
            {
                "started": started,
                "loop_run_id": loop_run_id,
                "runtime_state": dict(initial_state or {}),
                "iteration": 0,
                "iterations": [],
                "best_score": -1.0,
                "no_progress_rounds": 0,
                "fingerprints": {},
            }
        )

        last_result = final_state.get("last_result")
        if last_result is None:
            raise RuntimeError("loop stopped before the first action completed")
        stop_reason = final_state.get("stop_reason", StopReason.MAX_ITERATIONS)
        iterations = final_state.get("iterations", [])
        outcome = LoopOutcome(
            run_id=loop_run_id,
            objective=objective,
            success=stop_reason == StopReason.VERIFIED_SUCCESS,
            stop_reason=stop_reason,
            result=last_result,
            iterations=iterations,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            best_score=max((item.decision.score for item in iterations), default=0.0),
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

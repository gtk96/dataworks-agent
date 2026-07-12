"""Tests for the bounded Loop Engineering kernel."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from dataworks_agent.runtime.loop import (
    LoopDecision,
    LoopKernel,
    LoopPolicy,
    RepairResult,
    StopReason,
)


@dataclass
class Result:
    value: int


@pytest.mark.asyncio
async def test_loop_repairs_transient_failure_then_verifies():
    calls = 0

    async def action(state, iteration):
        nonlocal calls
        calls += 1
        return Result(calls)

    def verify(result, iteration):
        return LoopDecision(
            passed=result.value >= 2,
            score=1.0 if result.value >= 2 else 0.2,
            summary="ok" if result.value >= 2 else "temporary failure",
            failure_class="transient" if result.value < 2 else "",
            retryable=result.value < 2,
            action_fingerprint="query",
        )

    async def repair(state, result, decision, iteration):
        return RepairResult(True, "retry", "retry once")

    outcome = await LoopKernel(LoopPolicy(max_iterations=3)).run(
        objective="query orders", action=action, verify=verify, repair=repair
    )

    assert outcome.success is True
    assert outcome.stop_reason == StopReason.VERIFIED_SUCCESS
    assert calls == 2
    assert outcome.iterations[0].repair.action == "retry"


@pytest.mark.asyncio
async def test_loop_stops_non_retryable_without_repeating_action():
    calls = 0

    async def action(state, iteration):
        nonlocal calls
        calls += 1
        return Result(0)

    outcome = await LoopKernel().run(
        objective="missing table",
        action=action,
        verify=lambda result, iteration: LoopDecision(
            False, 0.0, "not found", failure_class="not_found", retryable=False
        ),
    )

    assert outcome.success is False
    assert outcome.stop_reason == StopReason.NON_RETRYABLE
    assert calls == 1


@pytest.mark.asyncio
async def test_loop_stops_for_clarification_without_false_success():
    async def action(state, iteration):
        return Result(0)

    outcome = await LoopKernel().run(
        objective="unknown metric",
        action=action,
        verify=lambda result, iteration: LoopDecision(
            False,
            0.5,
            "needs context",
            failure_class="needs_context",
            needs_context=True,
        ),
    )

    assert outcome.success is False
    assert outcome.stop_reason == StopReason.NEEDS_CONTEXT
    assert outcome.iterations[0].decision.passed is False


@pytest.mark.asyncio
async def test_loop_stops_repeated_identical_action():
    async def action(state, iteration):
        return Result(iteration)

    async def repair(state, result, decision, iteration):
        return RepairResult(True, "retry", "same action")

    outcome = await LoopKernel(
        LoopPolicy(max_iterations=5, max_same_action=2, max_no_progress_rounds=5)
    ).run(
        objective="retry forever",
        action=action,
        verify=lambda result, iteration: LoopDecision(
            False,
            0.1,
            "still failing",
            failure_class="transient",
            retryable=True,
            action_fingerprint="same-query",
        ),
        repair=repair,
    )

    assert outcome.stop_reason == StopReason.REPEATED_ACTION
    assert len(outcome.iterations) == 2

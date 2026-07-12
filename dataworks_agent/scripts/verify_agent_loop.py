"""Deterministic Agent Loop badcase gate used by CI."""

from __future__ import annotations

import json
from pathlib import Path

from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.agent.outcome_verifier import WorkflowOutcomeVerifier
from dataworks_agent.agent.workflow_service import AgentWorkflowService, WorkflowResult


def main() -> int:
    corpus_path = Path("tests/evaluation/agent_loop_badcases.json")
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))
    verifier = WorkflowOutcomeVerifier()
    parser = IntentParser()
    passed = 0
    false_successes: list[str] = []
    failures: list[dict[str, object]] = []

    for case in cases:
        if case["kind"] == "route":
            parsed = parser.parse(case["message"])
            actual = AgentWorkflowService._route_action(case["message"], parsed.action)
            ok = actual == case["expected"]
            details = {"actual": actual, "expected": case["expected"]}
        else:
            result = WorkflowResult(
                success=bool(case.get("raw_success")),
                message=str(case.get("message") or case["id"]),
                workflow_type=case["workflow_type"],
                mode=case["mode"],
                steps=case.get("steps", []),
                artifacts=case.get("artifacts", []),
                data=case.get("data", {}),
                errors=case.get("errors", []),
            )
            decision = verifier.verify(
                result,
                workflow_type=case["workflow_type"],
                mode=case["mode"],
                objective=case.get("objective", ""),
            )
            ok = decision.passed is bool(case["expected_passed"])
            if "expected_needs_context" in case:
                ok = ok and decision.needs_context is bool(case["expected_needs_context"])
            if case.get("raw_success") and not case["expected_passed"] and decision.passed:
                false_successes.append(case["id"])
            details = {
                "actual_passed": decision.passed,
                "expected_passed": case["expected_passed"],
                "stop_class": decision.failure_class,
                "needs_context": decision.needs_context,
            }
        if ok:
            passed += 1
        else:
            failures.append({"id": case["id"], **details})

    total = len(cases)
    report = {
        "corpus": str(corpus_path),
        "total": total,
        "passed": passed,
        "task_success_rate": passed / total if total else 0.0,
        "false_success_count": len(false_successes),
        "false_success_rate": len(false_successes) / total if total else 0.0,
        "false_success_cases": false_successes,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed == total and not false_successes else 1


if __name__ == "__main__":
    raise SystemExit(main())

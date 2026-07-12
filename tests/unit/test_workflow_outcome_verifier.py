"""Outcome contracts must prevent successful flags from becoming false success."""

from dataworks_agent.agent.outcome_verifier import WorkflowOutcomeVerifier
from dataworks_agent.agent.workflow_service import WorkflowResult


def test_ask_data_success_flag_without_verification_is_rejected():
    result = WorkflowResult(
        True,
        "query done",
        "ask_data",
        "dev_execute",
        data={"query": {"executed": True, "rows": [[1]]}},
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="ask_data", mode="dev_execute"
    )

    assert decision.passed is False
    assert decision.evidence["verification_status"] == "missing"


def test_forward_success_flag_with_failed_layer_is_rejected():
    result = WorkflowResult(
        True,
        "done",
        "forward_modeling",
        "dev_execute",
        steps=[{"step": "create_dwd", "status": "completed"}],
        data={
            "executed": [
                {"layer": "ODS", "result": {"success": True}},
                {"layer": "DWD", "result": {"success": False}},
            ],
            "publish_gate": "not_requested",
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="forward_modeling", mode="dev_execute"
    )

    assert decision.passed is False
    assert decision.evidence["failed_layers"] == ["DWD"]


def test_reverse_success_flag_without_real_metadata_is_rejected():
    result = WorkflowResult(
        True,
        "done",
        "reverse_modeling",
        "dev_execute",
        data={"source_type": "table", "table": "ods_orders", "columns": []},
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="reverse_modeling", mode="dev_execute"
    )

    assert decision.passed is False


def test_missing_diagnosis_target_becomes_needs_context():
    result = WorkflowResult(
        True,
        "not found",
        "diagnose_issue",
        "dev_execute",
        data={
            "needs_clarification": True,
            "clarifying_questions": ["confirm task id"],
            "target_requested": True,
            "target_resolved": False,
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="diagnose_issue", mode="dev_execute"
    )

    assert decision.passed is False
    assert decision.needs_context is True


def test_cookie_refresh_with_expired_raw_health_is_rejected():
    result = WorkflowResult(
        True,
        "refresh attempted",
        "cookie_manage",
        "dev_execute",
        data={
            "capabilities": {
                "cookie_bff": True,
                "cdp_9222": True,
                "cookie_health": "degraded",
                "cookie_mcp_health": "expired",
            }
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result,
        workflow_type="cookie_manage",
        mode="dev_execute",
        objective="refresh cookie",
    )

    assert decision.passed is False
    assert decision.failure_class == "authentication"


def test_ask_data_reconciliation_only_mismatch_is_retryable_freshness_lag():
    result = WorkflowResult(
        False,
        "query executed but reconciliation mismatched",
        "ask_data",
        "dev_execute",
        data={
            "query": {"executed": True, "rows": [[232]]},
            "reconciliation": {"status": "mismatch", "passed": False},
            "verification": {
                "status": "failed",
                "checks": [
                    {"name": "metadata_contract", "passed": True},
                    {"name": "result_reconciliation", "passed": False},
                ],
            },
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="ask_data", mode="dev_execute"
    )

    assert decision.passed is False
    assert decision.failure_class == "freshness_lag"
    assert decision.retryable is True
    assert decision.evidence["failed_checks"] == ["result_reconciliation"]
    assert decision.evidence["reconciliation_status"] == "mismatch"


def test_ask_data_metadata_failure_is_not_freshness_lag():
    result = WorkflowResult(
        False,
        "metadata validation failed",
        "ask_data",
        "dev_execute",
        data={
            "query": {"executed": True, "rows": [[232]]},
            "reconciliation": {"status": "mismatch", "passed": False},
            "verification": {
                "status": "failed",
                "checks": [
                    {"name": "metadata_contract", "passed": False},
                    {"name": "result_reconciliation", "passed": False},
                ],
            },
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="ask_data", mode="dev_execute"
    )

    assert decision.failure_class == "outcome_contract_failed"
    assert decision.retryable is False
    assert decision.evidence["failed_checks"] == [
        "metadata_contract",
        "result_reconciliation",
    ]

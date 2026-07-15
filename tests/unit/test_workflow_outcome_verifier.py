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


def test_standard_oss_approval_boundary_is_a_verified_terminal_state():
    result = WorkflowResult(
        True,
        "standard OSS flow completed",
        "forward_modeling",
        "dev_execute",
        steps=[
            {"step": step, "status": "completed"}
            for step in (
                "inspect_oss_directory",
                "profile_json_sample",
                "dmr_pub_column_check",
                "create_dev_tables_cookie",
                "create_ods_sql_node_cookie",
                "configure_ods_schedule_cookie",
                "create_dwd_sql_node_cookie",
                "configure_dwd_schedule_cookie",
                "configure_ods_to_dwd_dependency_cookie",
            )
        ]
        + [
            {"step": "create_prod_tables", "status": "approval_required"},
            {"step": "publish_gate", "status": "skipped"},
        ],
        data={
            "standard": "tiktok_smart_plus_material_report",
            "dev_tables": {"ods": "giikin_develop.ods_report", "dwd": "giikin_develop.dwd_report"},
            "prod_tables": {
                "ods": {"status": "approval_required"},
                "dwd": {"status": "approval_required"},
            },
            "ods_pipeline": {"success": True},
            "dwd_pipeline": {"success": True},
            "publish_gate": "not_requested",
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="forward_modeling", mode="dev_execute"
    )

    assert decision.passed is True
    assert decision.retryable is False
    assert decision.evidence["production_status"] == ["approval_required"]


def test_standard_oss_does_not_verify_when_dwd_pipeline_failed():
    result = WorkflowResult(
        True,
        "standard OSS flow incomplete",
        "forward_modeling",
        "dev_execute",
        steps=[
            {"step": "inspect_oss_directory", "status": "completed"},
            {"step": "profile_json_sample", "status": "completed"},
            {"step": "dmr_pub_column_check", "status": "completed"},
            {"step": "create_dev_tables_cookie", "status": "completed"},
            {"step": "create_ods_sql_node_cookie", "status": "completed"},
            {"step": "configure_ods_schedule_cookie", "status": "completed"},
            {"step": "create_dwd_sql_node_cookie", "status": "failed"},
            {"step": "configure_dwd_schedule_cookie", "status": "completed"},
            {"step": "configure_ods_to_dwd_dependency_cookie", "status": "completed"},
            {"step": "create_prod_tables", "status": "approval_required"},
            {"step": "publish_gate", "status": "skipped"},
        ],
        data={
            "standard": "tiktok_smart_plus_material_report",
            "dev_tables": {"ods": "giikin_develop.ods_report", "dwd": "giikin_develop.dwd_report"},
            "prod_tables": {
                "ods": {"status": "approval_required"},
                "dwd": {"status": "approval_required"},
            },
            "ods_pipeline": {"success": True},
            "dwd_pipeline": {"success": False},
            "publish_gate": "not_requested",
        },
    )

    decision = WorkflowOutcomeVerifier().verify(
        result, workflow_type="forward_modeling", mode="dev_execute"
    )

    assert decision.passed is False
    assert decision.retryable is False



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

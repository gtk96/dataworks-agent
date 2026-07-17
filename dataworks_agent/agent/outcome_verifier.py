"""Outcome contracts for conversational DataWorks workflows."""

from __future__ import annotations

from typing import Any

from dataworks_agent.runtime.shims import LoopDecision

_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "throttl",
    "too many requests",
    "429",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "internal server error",
    "csrf token expired",
    "cookie expired",
    "401 unauthorized",
)
_AUTH_MARKERS = ("cookie", "csrf", "unauthorized", "401", "\u767b\u5f55\u6001", "\u9274\u6743")
_PERMISSION_MARKERS = (
    "permission",
    "forbidden",
    "403",
    "no privilege",
    "\u6743\u9650",
    "\u7981\u6b62",
)
_NOT_FOUND_MARKERS = ("not found", "nosuchobject", "\u672a\u627e\u5230", "\u4e0d\u5b58\u5728")


def _status_score(steps: list[dict[str, Any]]) -> float:
    if not steps:
        return 0.0
    weights = {
        "completed": 1.0,
        "ok": 1.0,
        "planned": 1.0,
        "skipped": 1.0,
        "required_only_for_publish": 1.0,
        "approval_required": 1.0,
        "warning": 0.5,
        "blocked": 0.0,
        "failed": 0.0,
    }
    return sum(weights.get(str(step.get("status", "")).lower(), 0.0) for step in steps) / len(steps)


def _failure_details(result: Any) -> tuple[str, bool]:
    text = " ".join(str(item) for item in getattr(result, "errors", []) if item)
    text = f"{text} {getattr(result, 'message', '')}".lower()
    if any(marker in text for marker in _PERMISSION_MARKERS):
        return "permission_denied", False
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return "not_found", False
    if any(marker in text for marker in _AUTH_MARKERS):
        return "authentication", True
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return "transient", True
    return "outcome_contract_failed", False


class WorkflowOutcomeVerifier:
    """Verify observable outcomes instead of trusting a workflow success flag."""

    def verify(
        self,
        result: Any,
        *,
        workflow_type: str,
        mode: str,
        objective: str = "",
        publish_requested: bool = False,
    ) -> LoopDecision:
        data = getattr(result, "data", {}) or {}
        steps = getattr(result, "steps", []) or []
        base_score = _status_score(steps)
        needs_context = bool(data.get("needs_clarification") or data.get("clarifying_questions"))
        if needs_context:
            return LoopDecision(
                passed=False,
                score=max(base_score, 0.5),
                summary="Modeling result did not satisfy table, node, schedule, and publish contracts.",
                failure_class="needs_context",
                needs_context=True,
                evidence={"questions": data.get("clarifying_questions", [])},
            )

        if workflow_type == "ask_data":
            return self._verify_ask_data(result, mode, base_score)
        if workflow_type in ("forward_modeling", "any_ods_modeling"):
            return self._verify_forward(result, mode, base_score, publish_requested)
        if workflow_type == "reverse_modeling":
            return self._verify_reverse(result, base_score)
        if workflow_type == "diagnose_issue":
            return self._verify_diagnosis(result, base_score)
        if workflow_type == "cookie_manage":
            return self._verify_cookie(result, objective, base_score)
        return self._fallback(result, base_score, workflow_type)

    @staticmethod
    def _verify_ask_data(result: Any, mode: str, base_score: float) -> LoopDecision:
        data = result.data or {}
        query = data.get("query") or {}
        if mode == "plan":
            passed = bool(result.success and query.get("sql") and not query.get("executed"))
            return LoopDecision(
                passed=passed,
                score=1.0 if passed else base_score,
                summary="Read-only query plan generated."
                if passed
                else "Query plan is missing SQL or executed unexpectedly.",
                failure_class="" if passed else "query_plan_invalid",
                action_fingerprint="ask_data_plan",
                evidence={"sql_present": bool(query.get("sql")), "executed": query.get("executed")},
            )

        verification = data.get("verification") or {}
        checks = verification.get("checks") or []
        passed_checks = sum(1 for check in checks if check.get("passed"))
        score = passed_checks / len(checks) if checks else base_score
        passed = bool(
            result.success
            and query.get("executed") is True
            and verification.get("status") == "passed"
            and checks
            and passed_checks == len(checks)
        )
        if passed:
            return LoopDecision(
                passed=True,
                score=1.0,
                summary="Query executed and passed every outcome contract.",
                action_fingerprint="ask_data_verified",
                evidence={"passed_checks": passed_checks, "total_checks": len(checks)},
            )
        failed_checks = [
            str(check.get("name") or "") for check in checks if not check.get("passed")
        ]
        reconciliation = data.get("reconciliation") or {}
        freshness_lag = bool(
            query.get("executed") is True
            and verification.get("status") == "failed"
            and failed_checks == ["result_reconciliation"]
            and reconciliation.get("status") == "mismatch"
        )
        if freshness_lag:
            failure_class, retryable = "freshness_lag", True
        else:
            failure_class, retryable = _failure_details(result)
        return LoopDecision(
            passed=False,
            score=score,
            summary=(
                "DWS/DWD reconciliation is temporarily inconsistent; wait for metric refresh."
                if freshness_lag
                else "Query did not pass semantic, execution, and reconciliation checks."
            ),
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"ask_data:{failure_class}",
            evidence={
                "query_executed": query.get("executed", False),
                "verification_status": verification.get("status", "missing"),
                "passed_checks": passed_checks,
                "total_checks": len(checks),
                "failed_checks": failed_checks,
                "reconciliation_status": reconciliation.get("status", "missing"),
            },
        )

    @staticmethod
    def _verify_forward(
        result: Any, mode: str, base_score: float, publish_requested: bool
    ) -> LoopDecision:
        failed_steps = [
            step for step in result.steps if step.get("status") in {"failed", "blocked"}
        ]
        if mode == "plan":
            passed = bool(result.success and result.steps and not failed_steps)
            return LoopDecision(
                passed=passed,
                score=1.0 if passed else base_score,
                summary="Full-chain modeling plan passed deterministic checks."
                if passed
                else "Modeling plan contains failed steps.",
                failure_class="" if passed else "plan_validation_failed",
                evidence={"failed_steps": failed_steps},
            )

        data = result.data or {}
        executed = data.get("executed") or []
        failed_layers = [
            item.get("layer")
            for item in executed
            if not isinstance(item.get("result"), dict) or not item["result"].get("success")
        ]
        publish_gate = data.get("publish_gate")

        # The standard OSS flow has a richer contract than the generic
        # layer-by-layer flow: it returns separate ODS/DWD pipelines and
        # production DDL artifacts rather than an ``executed`` list. Treat
        # the production approval boundary as a valid terminal state; the
        # Publish Gate must remain in place and production must not be
        # published implicitly.
        if data.get("standard") == "tiktok_smart_plus_material_report":
            standard_steps = {
                str(step.get("step")): str(step.get("status")) for step in result.steps
            }
            required_steps = (
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
            failed_standard_steps = [
                step for step in required_steps if standard_steps.get(step) != "completed"
            ]
            ods_pipeline = data.get("ods_pipeline") or {}
            dwd_pipeline = data.get("dwd_pipeline") or {}
            prod_tables = data.get("prod_tables") or {}
            prod_statuses = {
                str((prod_tables.get(layer) or {}).get("status")) for layer in ("ods", "dwd")
            }
            standard_publish_ok = (
                standard_steps.get("create_prod_tables") == "approval_required"
                and standard_steps.get("publish_gate") in {"skipped", "approval_required"}
                and prod_statuses == {"approval_required"}
                and ods_pipeline.get("success") is True
                and dwd_pipeline.get("success") is True
                and bool(data.get("dev_tables"))
                and not failed_standard_steps
                and (not publish_requested or publish_gate == "approval_required")
            )
            if result.success and standard_publish_ok and not failed_steps:
                return LoopDecision(
                    passed=True,
                    score=1.0,
                    summary="Standard OSS development artifacts verified; production remains behind Publish Gate.",
                    evidence={
                        "standard": data.get("standard"),
                        "ods_pipeline": ods_pipeline.get("success"),
                        "dwd_pipeline": dwd_pipeline.get("success"),
                        "production_status": sorted(prod_statuses),
                        "publish_gate": publish_gate,
                    },
                )

        publish_ok = not publish_requested or publish_gate == "approval_required"
        passed = bool(
            result.success and executed and not failed_layers and not failed_steps and publish_ok
        )
        if passed:
            return LoopDecision(
                passed=True,
                score=1.0,
                summary="Development tables, nodes, schedules, and Publish Gate boundary verified.",
                evidence={
                    "layers": [item.get("layer") for item in executed],
                    "publish_gate": publish_gate,
                },
            )
        failure_class, retryable = _failure_details(result)
        score = base_score
        if executed:
            score = max(score, (len(executed) - len(failed_layers)) / len(executed))
        return LoopDecision(
            passed=False,
            score=score,
            summary="Modeling result did not satisfy table, node, schedule, and publish contracts.",
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"forward:{failure_class}",
            evidence={
                "executed_layers": len(executed),
                "failed_layers": failed_layers,
                "failed_steps": failed_steps,
                "publish_gate": publish_gate,
            },
        )

    @staticmethod
    def _verify_reverse(result: Any, base_score: float) -> LoopDecision:
        data = result.data or {}
        source_type = data.get("source_type")
        evidence_ok = False
        if source_type == "table":
            evidence_ok = bool(data.get("table") and (data.get("columns") or data.get("ddl")))
        elif source_type == "node":
            evidence_ok = bool(data.get("node") and data.get("flowspec"))
        elif source_type == "sql":
            evidence_ok = bool(data.get("sql") or getattr(result, "artifacts", []))
        passed = bool(result.success and source_type and evidence_ok)
        if passed:
            return LoopDecision(
                passed=True,
                score=1.0,
                summary="Reverse modeling produced traceable metadata or FlowSpec evidence.",
                evidence={"source_type": source_type, "artifact_count": len(result.artifacts)},
            )
        failure_class, retryable = _failure_details(result)
        return LoopDecision(
            passed=False,
            score=base_score,
            summary="Reverse modeling lacks table metadata, FlowSpec, or SQL evidence.",
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"reverse:{failure_class}",
            evidence={"source_type": source_type, "evidence_ok": evidence_ok},
        )

    @staticmethod
    def _verify_diagnosis(result: Any, base_score: float) -> LoopDecision:
        data = result.data or {}
        target_requested = bool(data.get("target_requested"))
        target_resolved = bool(data.get("target_resolved"))
        proposal = data.get("recovery_proposal") or {}
        evidence_sources = data.get("evidence_sources") or {}
        passed = bool(
            result.success
            and proposal.get("action")
            and (not target_requested or (target_resolved and evidence_sources))
        )
        if passed:
            return LoopDecision(
                passed=True,
                score=1.0,
                summary="Diagnosis resolved the target and produced a guarded recovery proposal.",
                evidence={
                    "target_resolved": target_resolved,
                    "action": proposal.get("action"),
                    "requires_approval": proposal.get("requires_approval", False),
                },
            )
        failure_class, retryable = _failure_details(result)
        return LoopDecision(
            passed=False,
            score=base_score,
            summary="Diagnosis did not resolve the requested target or evidence.",
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"diagnose:{failure_class}",
            evidence={"target_requested": target_requested, "target_resolved": target_resolved},
        )

    @staticmethod
    def _verify_cookie(result: Any, objective: str, base_score: float) -> LoopDecision:
        capabilities = (result.data or {}).get("capabilities") or {}
        refresh_requested = any(
            word in objective
            for word in (
                "refresh",
                "\u5237\u65b0",
                "\u66f4\u65b0",
                "\u91cd\u65b0\u767b\u5f55",
                "\u7eed\u671f",
            )
        )
        channel_available = bool(capabilities.get("cookie_bff") or capabilities.get("cdp_9222"))
        raw_health = capabilities.get("cookie_mcp_health", capabilities.get("cookie_health"))
        if refresh_requested:
            passed = bool(
                result.success and channel_available and raw_health not in {"expired", "critical"}
            )
        else:
            passed = bool(result.success and channel_available)
        if passed:
            return LoopDecision(
                passed=True,
                score=1.0,
                summary="Cookie/CDP fallback channel verified.",
                evidence={
                    "refresh_requested": refresh_requested,
                    "cookie_health": capabilities.get("cookie_health"),
                    "cookie_mcp_health": raw_health,
                },
            )
        failure_class, retryable = _failure_details(result)
        if refresh_requested and capabilities.get("cdp_9222"):
            failure_class, retryable = "authentication", True
        return LoopDecision(
            passed=False,
            score=base_score,
            summary="Cookie refresh or fallback verification failed.",
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"cookie:{failure_class}",
            evidence={"refresh_requested": refresh_requested, "capabilities": capabilities},
        )

    @staticmethod
    def _fallback(result: Any, base_score: float, workflow_type: str) -> LoopDecision:
        if result.success:
            return LoopDecision(True, 1.0, "Workflow passed the generic outcome contract.")
        failure_class, retryable = _failure_details(result)
        return LoopDecision(
            False,
            base_score,
            "Workflow did not pass the generic outcome contract.",
            failure_class=failure_class,
            retryable=retryable,
            action_fingerprint=f"{workflow_type}:{failure_class}",
        )

"""Dry-run/proposal tool executor used by the chat Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Result returned by one Agent tool step."""

    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


class ToolExecutor:
    """Execute Agent tools in safe proposal mode.

    The chat Agent should be useful locally without accidentally mutating a
    DataWorks workspace. These handlers therefore validate inputs, draft
    artifacts, and explain the AK/SK vs Cookie execution route instead of
    performing destructive online operations directly.
    """

    def execute(self, tool: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        handler = getattr(self, f"_execute_{tool}", None)
        if handler is None:
            return ToolResult(
                tool=tool,
                success=True,
                data={
                    "mode": "dry_run",
                    "summary": f"No concrete handler is registered for {tool}; recorded as a dry-run step.",
                    "params": params,
                },
                warnings=["This step did not call DataWorks. Add a concrete handler before online execution."],
            )
        return handler(params)

    def _execute_validate_table_request(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name")
        if not table_name:
            return ToolResult(
                tool="validate_table_request",
                success=False,
                error="missing_table_name",
                data={"required": ["table_name"]},
            )
        try:
            from dataworks_agent.schemas import assert_safe_table_name

            assert_safe_table_name(str(table_name))
        except ValueError as exc:
            return ToolResult(
                tool="validate_table_request",
                success=False,
                error="invalid_table_name",
                data={"detail": str(exc), "table_name": table_name},
            )
        return ToolResult(
            tool="validate_table_request",
            success=True,
            data={
                "mode": "guardrail",
                "summary": "Table request passed deterministic guardrails.",
                "checks": ["safe_table_name", "destructive_guard_required", "publish_gate_required"],
                "table_name": table_name,
                "layer": params.get("layer"),
            },
        )

    def _execute_create_holo_table(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="create_holo_table",
            success=True,
            data={
                "mode": "proposal",
                "summary": "Draft a Hologres/ODS table creation plan.",
                "artifact_type": "holo_or_ods_table_draft",
                "table_name": params.get("table_name"),
                "source_table": params.get("source_table"),
                "notes": ["Holo SQL should stay in DataWorks HOLOGRES_SQL nodes; this agent does not connect to Holo directly."],
            },
        )

    def _execute_create_mc_table(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name") or "<target_table>"
        source_table = params.get("source_table") or "<source_table>"
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
            "  id STRING COMMENT 'business id',\n"
            "  update_time DATETIME COMMENT '业务更新时间'\n"
            ") PARTITIONED BY (ds STRING COMMENT '业务日期') LIFECYCLE 365;"
        )
        return ToolResult(
            tool="create_mc_table",
            success=True,
            data={
                "mode": "draft",
                "summary": f"Draft a MaxCompute DDL scaffold from {source_table}.",
                "artifact_type": "maxcompute_ddl",
                "ddl": ddl,
                "table_name": table_name,
                "source_table": source_table,
            },
            warnings=["DDL is a scaffold. Review columns, comments, partition keys, and lifecycle before publishing."],
        )

    def _execute_create_node(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name") or "<target_table>"
        layer = (params.get("layer") or "dwd").upper()
        return ToolResult(
            tool="create_node",
            success=True,
            data={
                "mode": "draft",
                "summary": "Draft a DataWorks FlowSpec node outline.",
                "artifact_type": "flowspec_outline",
                "path": f"business_flow/<domain>/MaxCompute/data_development/{layer}/{table_name}",
                "runtime": {"command": "ODPS_SQL", "commandTypeId": 10},
                "publish_gate": "required",
            },
        )

    def _execute_push_dml(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name") or "<target_table>"
        source_table = params.get("source_table") or "<source_table>"
        sql = (
            f"INSERT OVERWRITE TABLE {table_name} PARTITION (ds='${{bizdate}}')\n"
            f"SELECT\n  *\nFROM {source_table}\nWHERE ds = '${{bizdate}}';"
        )
        return ToolResult(
            tool="push_dml",
            success=True,
            data={
                "mode": "proposal",
                "summary": "Plan DML push, dependency wiring, and schedule parameters.",
                "artifact_type": "dml_and_dependency_plan",
                "table_name": table_name,
                "source_table": source_table,
                "sql": sql,
                "requires_approval": True,
            },
        )

    def _execute_query_lineage(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name")
        if not table_name:
            return ToolResult(
                tool="query_lineage",
                success=False,
                error="missing_table_name",
                data={"required": ["table_name"]},
            )
        return ToolResult(
            tool="query_lineage",
            success=True,
            data={
                "mode": "read_plan",
                "summary": "Plan a lineage/dependency query for the target table.",
                "table_name": table_name,
                "depth": params.get("depth", 3),
                "lineage": {
                    "target": table_name,
                    "depth": params.get("depth", 3),
                    "status": "planned",
                },
                "routes": [
                    {"scope": "node dependencies", "preferred": "AK/SK ListNodeDependencies"},
                    {"scope": "downstream DAG", "preferred": "Cookie BFF fallback"},
                ],
            },
        )

    def _execute_summarize_lineage_impact(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="summarize_lineage_impact",
            success=True,
            data={
                "mode": "analysis",
                "summary": "Prepare a lineage impact summary.",
                "artifact_type": "lineage_impact_summary",
                "lineage": {
                    "table_name": params.get("table_name"),
                    "sections": ["upstreams", "downstreams", "schedule risk", "data quality", "recommended actions"],
                },
                "table_name": params.get("table_name"),
            },
        )

    def _execute_check_task_status(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="check_task_status",
            success=True,
            data={
                "mode": "status",
                "summary": "Read the latest Agent task status.",
                "task_id": params.get("task_id"),
                "hint": "Omit task_id to inspect the latest task in this Agent instance.",
            },
        )

    def _execute_analyze_requirement(self, params: dict[str, Any]) -> ToolResult:
        goal = params.get("goal") or ""
        missing: list[str] = []
        if not params.get("table_name"):
            missing.append("target table")
        if not params.get("source_table") and any(word in goal.lower() for word in ("建模", "model", "dwd", "dws", "dim")):
            missing.append("source table")
        return ToolResult(
            tool="analyze_requirement",
            success=True,
            data={
                "mode": "analysis",
                "summary": "Analyze the DataWorks request and identify missing context.",
                "goal": goal,
                "table_name": params.get("table_name"),
                "source_table": params.get("source_table"),
                "layer": params.get("layer"),
                "missing_context": missing,
            },
            warnings=["More context is needed before online execution."] if missing else [],
        )

    def _execute_collect_context(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="collect_context",
            success=True,
            data={
                "mode": "read_plan",
                "summary": "Prepare context collection across workspace metadata, lineage, governance, and artifacts.",
                "artifact_type": "context_collection_plan",
                "sources": ["workspace metadata", "lineage graph", "governance checks", "existing artifacts", "task history"],
                "table_name": params.get("table_name"),
                "source_table": params.get("source_table"),
            },
        )

    def _execute_plan_dataworks_workflow(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="plan_dataworks_workflow",
            success=True,
            data={
                "mode": "plan",
                "summary": "Draft an end-to-end DataWorks workflow.",
                "workflow": ["requirement analysis", "context collection", "DDL/DML draft", "FlowSpec draft", "guardrails", "approval", "publish"],
            },
        )

    def _execute_validate_guardrails(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name")
        if table_name:
            return self._execute_validate_table_request(params)
        return ToolResult(
            tool="validate_guardrails",
            success=True,
            data={
                "mode": "guardrail",
                "summary": "Guardrail checklist prepared; table-specific checks need table_name.",
                "checks": ["B1 import path", "B2 destructive guard", "B3 table identifier", "Publish Gate"],
                "requires_approval": True,
            },
            warnings=["No table_name was provided, so the B3 identifier check was not executed."],
        )

    def _execute_draft_execution_artifacts(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="draft_execution_artifacts",
            success=True,
            data={
                "mode": "draft",
                "summary": "Draft execution artifacts for review.",
                "artifacts": ["DDL scaffold", "DML scaffold", "FlowSpec outline", "dependency plan", "schedule plan"],
                "schedule": {"cycle": params.get("schedule_cycle") or "daily", "parameter": "bizdate"},
                "risk_report": {"publish_gate": "required", "destructive_guard": "required", "online_writes": "blocked in proposal mode"},
                "requires_approval": True,
            },
        )

    def _execute_forward_modeling_dry_run(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name") or "<target_table>"
        source_table = params.get("source_table") or "<source_table>"
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
            "  id STRING COMMENT 'business id',\n"
            "  update_time DATETIME COMMENT '业务更新时间'\n"
            ") PARTITIONED BY (ds STRING COMMENT '业务日期') LIFECYCLE 365;"
        )
        sql = (
            f"INSERT OVERWRITE TABLE {table_name} PARTITION (ds='${{bizdate}}')\n"
            f"SELECT\n  *\nFROM {source_table}\nWHERE ds = '${{bizdate}}';"
        )
        return ToolResult(
            tool="forward_modeling_dry_run",
            success=True,
            data={
                "mode": "draft",
                "summary": "Generate a forward modeling dry-run package without writing to DataWorks.",
                "artifact_type": "forward_modeling_dry_run",
                "table_name": table_name,
                "source_table": source_table,
                "ddl": ddl,
                "sql": sql,
                "schedule": {"cycle": params.get("schedule_cycle") or "daily", "parameter": "bizdate"},
                "requires_approval": True,
            },
            warnings=["This is a scaffold. Connect ModelingEngine for production-grade DDL/DML generation before publish."],
        )

    def _execute_reverse_modeling_inspect(self, params: dict[str, Any]) -> ToolResult:
        table_name = params.get("table_name") or params.get("source_table") or "<existing_table>"
        return ToolResult(
            tool="reverse_modeling_inspect",
            success=True,
            data={
                "mode": "read_plan",
                "summary": "Plan reverse modeling inspection for an existing table.",
                "artifact_type": "reverse_modeling_inspection",
                "table_name": table_name,
                "lineage": {"target": table_name, "status": "to_inspect"},
            },
        )

    def _execute_diagnose_metric_attribution(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="diagnose_metric_attribution",
            success=True,
            data={
                "mode": "analysis",
                "summary": "Prepare metric attribution diagnosis using semantic metadata and lineage only.",
                "artifact_type": "metric_attribution_plan",
                "metric_id": params.get("metric_id"),
                "risk_report": {"row_data_to_llm": "blocked", "semantic_definition_required": True},
            },
        )

    def _execute_diagnose_self_heal(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="diagnose_self_heal",
            success=True,
            data={
                "mode": "analysis",
                "summary": "Prepare a self-heal diagnosis and recovery proposal.",
                "artifact_type": "self_heal_proposal",
                "task_id": params.get("task_id"),
                "risk_report": {"auto_recovery": "proposal_only", "approval_required_for_mutation": True},
                "requires_approval": True,
            },
        )

    def _execute_publish_gate_review(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="publish_gate_review",
            success=True,
            data={
                "mode": "approval_required",
                "summary": "Prepare Publish Gate review. Direct online publish is blocked in Agent proposal mode.",
                "artifact_type": "publish_gate_review",
                "table_name": params.get("table_name"),
                "publish_gate": "required",
                "requires_approval": True,
                "risk_report": {"online_write": "blocked", "delete_or_overwrite": "requires explicit approval"},
            },
            warnings=["Agent stopped at the approval boundary; no online publish was executed."],
        )

    def _execute_recommend_next_actions(self, params: dict[str, Any]) -> ToolResult:
        actions = [
            "确认源表、目标表、负责人和调度周期。",
            "先运行 dry-run 生成 DDL、DML 和 FlowSpec 产物。",
            "发布、删除、覆盖等线上写操作必须经过 Publish Gate 审批。",
        ]
        return ToolResult(
            tool="recommend_next_actions",
            success=True,
            data={"mode": "next_actions", "summary": "Recommended next actions prepared.", "actions": actions},
        )

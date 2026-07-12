"""Dry-run/proposal tool executor used by the chat Agent."""

from __future__ import annotations

import re
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
                warnings=[
                    "This step did not call DataWorks. Add a concrete handler before online execution."
                ],
            )
        return handler(params)

    @staticmethod
    def _clean_identifier_part(value: Any, *, fallback: str = "unknown") -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
        return cleaned or fallback

    @classmethod
    def _source_name_part(cls, value: Any, *, fallback: str = "table") -> str:
        text = str(value or "").strip().strip("/\\")
        if not text:
            return fallback
        if "://" in text or "/" in text or "\\" in text:
            segment = re.split(r"[/\\]", text.split("?", 1)[0].rstrip("/\\"))[-1]
            segment = segment.replace("*", "")
            if "." in segment:
                segment = segment.rsplit(".", 1)[0]
        else:
            segment = text.split(".")[-1]
        return cls._clean_identifier_part(segment, fallback=fallback)

    @staticmethod
    def _normalize_granularity(value: Any) -> str:
        text = str(value or "day").strip().lower()
        if text in {"hour", "hourly", "\u5c0f\u65f6", "\u6bcf\u5c0f\u65f6"}:
            return "hour"
        if text in {"minute", "min", "\u5206\u949f"}:
            return "minute"
        if text in {"realtime", "real_time", "\u5b9e\u65f6", "cdc"}:
            return "realtime"
        if text in {"full", "all", "\u5168\u91cf"}:
            return "full"
        return "day"

    @staticmethod
    def _normalize_source_type(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        mapping = {
            "holo": "hologres",
            "hologres": "hologres",
            "mysql": "mysql",
            "polardb": "polardb",
            "polar": "polardb",
            "postgresql": "postgres",
            "postgres": "postgres",
            "oracle": "oracle",
            "sqlserver": "sqlserver",
            "oss": "oss",
            "s3": "oss",
            "realtime": "realtime",
            "real_time": "realtime",
            "cdc": "realtime",
            "flink": "realtime",
            "binlog": "realtime",
        }
        return mapping.get(text, text or None)

    def _infer_dwd_table(self, params: dict[str, Any]) -> str | None:
        table_name = params.get("dwd_table") or params.get("table_name")
        if table_name:
            return str(table_name)
        ods_table = params.get("ods_table") or params.get("source_table")
        if isinstance(ods_table, str) and ods_table.lower().startswith("ods_"):
            base = ods_table[4:]
            for suffix in ("_hour", "_day"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
            return f"dwd_{base}_detail"
        return None

    def _infer_ods_table(self, params: dict[str, Any]) -> str | None:
        ods_table = params.get("ods_table")
        if ods_table:
            return str(ods_table)
        source_table = params.get("source_table") or params.get("oss_path")
        if isinstance(source_table, str) and source_table.lower().startswith("ods_"):
            return source_table
        if not source_table:
            return None
        datasource = self._clean_identifier_part(params.get("datasource_name"), fallback="src")
        source_name = self._source_name_part(source_table, fallback="table")
        source_type = self._normalize_source_type(params.get("source_type")) or "mysql"
        granularity = self._normalize_granularity(params.get("granularity"))
        if granularity == "realtime":
            granularity = "hour"
        try:
            if source_type == "realtime":
                from dataworks_agent.naming import generate_ods_realtime_table_name

                return generate_ods_realtime_table_name(datasource, source_name, granularity)
            from dataworks_agent.naming import generate_ods_di_table_name

            return generate_ods_di_table_name(
                datasource, source_name, granularity, source_type=source_type
            )
        except Exception:
            return f"ods_{source_type}_{datasource}__{source_name}_{granularity}"

    def _classify_ods_route(self, params: dict[str, Any]) -> dict[str, Any]:
        source_type = self._normalize_source_type(params.get("source_type"))
        source_table = params.get("source_table")
        ods_table = params.get("ods_table")
        if (isinstance(source_table, str) and source_table.lower().startswith("ods_")) or ods_table:
            return {
                "route": "existing_ods",
                "pipeline": "skip_ods_create",
                "module": None,
                "reason": "Conversation already points to an ODS table; only DWD preview/dependency planning is needed.",
            }
        if source_type in {
            "mysql",
            "polardb",
            "postgres",
            "oracle",
            "sqlserver",
            "mongodb",
            "mongo",
            "elasticsearch",
            "ftp",
            "maxcompute",
            "odps",
        }:
            return {
                "route": "ods_di",
                "pipeline": "DIPipeline.run",
                "module": "dataworks_agent.services.ods_di.pipeline",
                "reason": "Batch source uses DataWorks data integration node and MaxCompute ODS table creation.",
            }
        if source_type == "hologres":
            return {
                "route": "ods_holo",
                "pipeline": "ods_holo ensure_table + build_holo_ods_dml + HOLOGRES_SQL node",
                "module": "dataworks_agent.services.ods_holo",
                "reason": "Hologres source keeps IMPORT/DML inside DataWorks HOLOGRES_SQL nodes.",
            }
        if source_type == "oss":
            return {
                "route": "ods_oss",
                "pipeline": "OssImportPipeline.run",
                "module": "dataworks_agent.services.ods_oss.pipeline",
                "reason": "OSS file import uses the dedicated ODS OSS pipeline.",
            }
        if source_type == "realtime":
            return {
                "route": "ods_realtime",
                "pipeline": "RealtimeSyncPipeline.run",
                "module": "dataworks_agent.services.ods_realtime.pipeline",
                "reason": "CDC/realtime sync uses delta-to-ODS realtime pipeline.",
            }
        return {
            "route": "needs_context",
            "pipeline": None,
            "module": None,
            "reason": "Missing or unsupported source_type; ask user to choose DI/Hologres/OSS/Realtime route.",
        }

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
                "checks": [
                    "safe_table_name",
                    "destructive_guard_required",
                    "publish_gate_required",
                ],
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
                "notes": [
                    "Holo SQL should stay in DataWorks HOLOGRES_SQL nodes; this agent does not connect to Holo directly."
                ],
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
            warnings=[
                "DDL is a scaffold. Review columns, comments, partition keys, and lifecycle before publishing."
            ],
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
                    "sections": [
                        "upstreams",
                        "downstreams",
                        "schedule risk",
                        "data quality",
                        "recommended actions",
                    ],
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
        if not params.get("source_table") and any(
            word in goal.lower() for word in ("建模", "model", "dwd", "dws", "dim")
        ):
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
                "sources": [
                    "workspace metadata",
                    "lineage graph",
                    "governance checks",
                    "existing artifacts",
                    "task history",
                ],
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
                "workflow": [
                    "requirement analysis",
                    "context collection",
                    "DDL/DML draft",
                    "FlowSpec draft",
                    "guardrails",
                    "approval",
                    "publish",
                ],
            },
        )

    def _execute_validate_guardrails(self, params: dict[str, Any]) -> ToolResult:
        identifiers = {
            key: value
            for key in ("table_name", "dwd_table", "ods_table")
            if (value := params.get(key))
        }
        if identifiers:
            checks: dict[str, str] = {}
            errors: dict[str, str] = {}
            try:
                from dataworks_agent.schemas import assert_safe_table_name

                for key, value in identifiers.items():
                    try:
                        assert_safe_table_name(str(value))
                        checks[key] = "passed"
                    except ValueError as exc:
                        checks[key] = "failed"
                        errors[key] = str(exc)
            except Exception as exc:
                return ToolResult(
                    tool="validate_guardrails",
                    success=False,
                    error="guardrail_import_failed",
                    data={"detail": str(exc)},
                )
            if errors:
                return ToolResult(
                    tool="validate_guardrails",
                    success=False,
                    error="invalid_table_name",
                    data={"mode": "guardrail", "checks": checks, "errors": errors},
                )
            return ToolResult(
                tool="validate_guardrails",
                success=True,
                data={
                    "mode": "guardrail",
                    "summary": "Table identifiers passed deterministic guardrails.",
                    "checks": {
                        "safe_table_name": checks,
                        "destructive_guard_required": True,
                        "publish_gate_required": True,
                    },
                    **identifiers,
                },
            )
        return ToolResult(
            tool="validate_guardrails",
            success=True,
            data={
                "mode": "guardrail",
                "summary": "Guardrail checklist prepared; table-specific checks need table_name.",
                "checks": [
                    "B1 import path",
                    "B2 destructive guard",
                    "B3 table identifier",
                    "Publish Gate",
                ],
                "requires_approval": True,
            },
            warnings=[
                "No table_name/ods_table/dwd_table was provided, so the B3 identifier check was not executed."
            ],
        )

    def _execute_draft_execution_artifacts(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool="draft_execution_artifacts",
            success=True,
            data={
                "mode": "draft",
                "summary": "Draft execution artifacts for review.",
                "artifacts": [
                    "DDL scaffold",
                    "DML scaffold",
                    "FlowSpec outline",
                    "dependency plan",
                    "schedule plan",
                ],
                "schedule": {
                    "cycle": params.get("schedule_cycle") or "daily",
                    "parameter": "bizdate",
                },
                "risk_report": {
                    "publish_gate": "required",
                    "destructive_guard": "required",
                    "online_writes": "blocked in proposal mode",
                },
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
                "schedule": {
                    "cycle": params.get("schedule_cycle") or "daily",
                    "parameter": "bizdate",
                },
                "requires_approval": True,
            },
            warnings=[
                "This is a scaffold. Connect ModelingEngine for production-grade DDL/DML generation before publish."
            ],
        )

    def _execute_analyze_ods_dwd_requirement(self, params: dict[str, Any]) -> ToolResult:
        ods_table = self._infer_ods_table(params)
        dwd_table = self._infer_dwd_table(params)
        source_type = self._normalize_source_type(params.get("source_type"))
        granularity = self._normalize_granularity(params.get("granularity"))
        missing: list[str] = []
        source_table = params.get("source_table") or params.get("oss_path")
        if not ods_table and not source_table:
            missing.append("source_table/oss_path or ods_table")
        if (
            not params.get("ods_table")
            and not source_type
            and not str(source_table or "").lower().startswith("ods_")
        ):
            missing.append("source_type")
        if not dwd_table:
            missing.append("dwd_table")
        if source_type and source_type not in {
            "mysql",
            "polardb",
            "postgres",
            "oracle",
            "sqlserver",
            "hologres",
            "oss",
            "realtime",
            "mongodb",
            "mongo",
            "elasticsearch",
            "ftp",
            "maxcompute",
            "odps",
        }:
            missing.append("supported_source_type")

        return ToolResult(
            tool="analyze_ods_dwd_requirement",
            success=True,
            data={
                "mode": "analysis",
                "summary": "Analyze conversational ODS+DWD modeling request and normalize core parameters.",
                "artifact_type": "ods_dwd_requirement",
                "goal": params.get("goal"),
                "source_type": source_type,
                "datasource_name": params.get("datasource_name"),
                "source_table": params.get("source_table"),
                "oss_path": params.get("oss_path"),
                "ods_table": ods_table,
                "dwd_table": dwd_table,
                "table_name": dwd_table,
                "granularity": granularity,
                "schedule_cycle": params.get("schedule_cycle")
                or ("hourly" if granularity == "hour" else "daily"),
                "schedule_minute": params.get("schedule_minute"),
                "missing_context": missing,
                "requires_approval_for_online_write": True,
            },
            warnings=["Missing context must be filled before real ODS/DWD execution."]
            if missing
            else [],
        )

    def _execute_classify_ods_source(self, params: dict[str, Any]) -> ToolResult:
        route = self._classify_ods_route(params)
        source_type = self._normalize_source_type(params.get("source_type"))
        return ToolResult(
            tool="classify_ods_source",
            success=True,
            data={
                "mode": "plan",
                "summary": "Select the deterministic ODS capability route for the conversation.",
                "artifact_type": "ods_route",
                "source_type": source_type,
                "ods_route": route,
                "capability_matrix": {
                    "batch_database": "DIPipeline.run (DI node + MaxCompute table)",
                    "hologres": "ods_holo DataWorks HOLOGRES_SQL node",
                    "oss": "OssImportPipeline.run",
                    "realtime": "RealtimeSyncPipeline.run",
                    "existing_ods": "Skip ODS creation and continue with DWD",
                },
            },
            warnings=[route["reason"]] if route["route"] == "needs_context" else [],
        )

    def _execute_plan_ods_pipeline(self, params: dict[str, Any]) -> ToolResult:
        route = self._classify_ods_route(params)
        ods_table = self._infer_ods_table(params)
        granularity = self._normalize_granularity(params.get("granularity"))
        source_type = self._normalize_source_type(params.get("source_type"))
        source_table = params.get("source_table") or params.get("oss_path")
        datasource_name = params.get("datasource_name")
        validation: dict[str, Any] = {"safe_table_name": "not_checked"}
        if ods_table:
            try:
                from dataworks_agent.schemas import assert_safe_table_name

                assert_safe_table_name(ods_table)
                validation["safe_table_name"] = "passed"
            except ValueError as exc:
                validation["safe_table_name"] = "failed"
                validation["error"] = str(exc)

        missing = []
        if route["route"] != "existing_ods":
            if not source_table:
                missing.append("source_table")
            if route["route"] in {"ods_di", "ods_holo"} and not datasource_name:
                missing.append("datasource_name")
            if route["route"] == "needs_context":
                missing.append("source_type")
        if not ods_table:
            missing.append("ods_table")

        plan = {
            "route": route["route"],
            "pipeline": route["pipeline"],
            "module": route["module"],
            "mode": "dry_run_plan",
            "source_type": source_type,
            "datasource_name": datasource_name,
            "source_table": source_table,
            "oss_path": params.get("oss_path"),
            "target_table": ods_table,
            "granularity": granularity,
            "script_path": "dataworks_agent/01_ODS",
            "schedule_minute": params.get("schedule_minute")
            if params.get("schedule_minute") is not None
            else 1,
            "validation": validation,
            "missing_context": missing,
            "online_boundary": {
                "create_table": "AK/SK MaxCompute or existing ODS helper",
                "create_node": "AK/SK DataWorks node APIs when available",
                "metadata_browse": "Cookie fallback where AK/SK has 403 by design",
                "publish": "Publish Gate required",
            },
        }
        return ToolResult(
            tool="plan_ods_pipeline",
            success=True,
            data={
                "mode": "plan",
                "summary": "Plan the ODS pipeline without mutating DataWorks.",
                "artifact_type": "ods_pipeline_plan",
                "ods_plan": plan,
                "requires_approval": True,
            },
            warnings=["ODS plan still needs missing context before execution."] if missing else [],
        )

    def _execute_preview_dwd_artifacts(self, params: dict[str, Any]) -> ToolResult:
        dwd_table = self._infer_dwd_table(params)
        ods_table = self._infer_ods_table(params)
        if not dwd_table or not ods_table:
            return ToolResult(
                tool="preview_dwd_artifacts",
                success=True,
                data={
                    "mode": "needs_context",
                    "summary": "DWD preview needs both ods_table/source_table and dwd_table.",
                    "artifact_type": "dwd_preview",
                    "ods_table": ods_table,
                    "dwd_table": dwd_table,
                    "missing_context": [
                        item
                        for item, value in {"ods_table": ods_table, "dwd_table": dwd_table}.items()
                        if not value
                    ],
                    "dwd_preview_capability": True,
                },
                warnings=[
                    "Provide ODS and DWD table names to render deterministic DDL/SQL preview."
                ],
            )

        granularity = self._normalize_granularity(params.get("granularity"))
        update_mode = (
            "hourly" if granularity == "hour" else "full" if granularity == "full" else "daily"
        )
        partition_fields = ["dt", "ht"] if update_mode == "hourly" else ["dt"]
        target_fields = [
            {"name": "id", "type": "STRING", "comment": "business primary key"},
            {"name": "updated_at", "type": "DATETIME", "comment": "business update time"},
            {"name": "source_table", "type": "STRING", "comment": "source table marker"},
        ]
        target_fields.extend(
            {"name": pf, "type": "STRING", "comment": "partition field"} for pf in partition_fields
        )
        structured_metadata = {
            "targets": [
                {
                    "table_name": dwd_table,
                    "table_comment": f"{dwd_table} conversational DWD preview",
                    "update_mode": update_mode,
                    "partition_fields": partition_fields,
                    "logical_primary_keys": ["id"],
                    "fields": target_fields,
                }
            ],
            "sources": [{"table_name": ods_table, "alias": "T1", "is_master": True}],
            "field_mappings": [
                {
                    "source_alias": "T1",
                    "source_field_name": "id",
                    "target_field_name": "id",
                    "field_category": "normal",
                },
                {
                    "source_alias": "T1",
                    "source_field_name": "updated_at",
                    "target_field_name": "updated_at",
                    "field_category": "normal",
                    "apply_coalesce": False,
                },
                {
                    "source_alias": "T1",
                    "source_field_name": "source_table",
                    "target_field_name": "source_table",
                    "transform_sql": f"'{ods_table}'",
                    "field_category": "normal",
                    "apply_coalesce": False,
                },
            ],
            "joins": [],
        }
        try:
            from dataworks_agent.modeling.dwd.ddl_generator import DwdDDLGenerator
            from dataworks_agent.modeling.dwd.metadata import build_structured_metadata
            from dataworks_agent.modeling.dwd.sql_generator import DwdSQLGenerator

            ddl_gen = DwdDDLGenerator()
            ddl = ddl_gen.generate(ddl_gen.from_structured_metadata(structured_metadata))
            sql = DwdSQLGenerator().generate(build_structured_metadata(structured_metadata))
        except Exception as exc:
            return ToolResult(
                tool="preview_dwd_artifacts",
                success=False,
                error="dwd_preview_failed",
                data={
                    "detail": str(exc),
                    "structured_metadata": structured_metadata,
                    "ods_table": ods_table,
                    "dwd_table": dwd_table,
                },
            )

        return ToolResult(
            tool="preview_dwd_artifacts",
            success=True,
            data={
                "mode": "draft",
                "summary": "Render deterministic DWD DDL/SQL preview from normalized ODS+DWD context.",
                "artifact_type": "dwd_preview",
                "dwd_preview": {
                    "target_table": dwd_table,
                    "source_table": ods_table,
                    "update_mode": update_mode,
                    "partition_fields": partition_fields,
                    "structured_metadata": structured_metadata,
                    "ddl": ddl,
                    "sql": sql,
                    "pipeline": "DwdDeployPipeline.preview_ddl/preview_sql",
                },
                "table_name": dwd_table,
                "source_table": ods_table,
                "ddl": ddl,
                "sql": sql,
                "schedule": {
                    "cycle": "hourly" if update_mode == "hourly" else "daily",
                    "parameters": ["gmtdate", "hour_last1h"]
                    if update_mode == "hourly"
                    else ["bizdate", "pre_bizdate"],
                },
                "requires_approval": True,
            },
            warnings=[
                "Preview uses a minimal field mapping scaffold; replace with real metadata before publish."
            ],
        )

    def _execute_plan_ods_dwd_dependencies(self, params: dict[str, Any]) -> ToolResult:
        ods_table = self._infer_ods_table(params)
        dwd_table = self._infer_dwd_table(params)
        granularity = self._normalize_granularity(params.get("granularity"))
        dependency_plan = {
            "mode": "dry_run_plan",
            "upstream_refs": [f"dataworks.{ods_table}"] if ods_table else [],
            "target_output": f"dataworks.{dwd_table}" if dwd_table else None,
            "flow_depends": [
                {
                    "type": "Normal",
                    "sourceType": "Manual",
                    "output": f"dataworks.{ods_table}",
                    "refTableName": f"dataworks.{ods_table}",
                }
            ]
            if ods_table
            else [],
            "self_dependency": {"type": "CrossCycleDependsOnSelf"},
            "schedule": {
                "cycle": "hourly" if granularity == "hour" else "daily",
                "minute": params.get("schedule_minute")
                if params.get("schedule_minute") is not None
                else 1,
            },
            "publish_gate": "required",
        }
        return ToolResult(
            tool="plan_ods_dwd_dependencies",
            success=True,
            data={
                "mode": "plan",
                "summary": "Plan ODS+DWD node dependencies and scheduling without writing FlowSpec.",
                "artifact_type": "dependency_plan",
                "dependency_plan": dependency_plan,
                "lineage": {"upstream": ods_table, "downstream": dwd_table, "status": "planned"},
                "requires_approval": True,
            },
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
                "risk_report": {
                    "auto_recovery": "proposal_only",
                    "approval_required_for_mutation": True,
                },
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
                "risk_report": {
                    "online_write": "blocked",
                    "delete_or_overwrite": "requires explicit approval",
                },
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
            data={
                "mode": "next_actions",
                "summary": "Recommended next actions prepared.",
                "actions": actions,
            },
        )

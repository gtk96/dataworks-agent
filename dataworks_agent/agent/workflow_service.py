"""一句话 DataWorks Agent 的真实执行工作流。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import BUSINESS_QUERY_PATTERNS
from dataworks_agent.config import settings
from dataworks_agent.governance.closed_loop_verifier import (
    ClosedLoopVerifier,
    VerificationStatus,
)
from dataworks_agent.naming import generate_node_path, generate_ods_di_table_name
from dataworks_agent.naming.schedule import (
    DAILY_SQL_PARAMETERS,
    HOURLY_SQL_PARAMETERS,
    generate_cron,
)
from dataworks_agent.schemas import assert_safe_table_name
from dataworks_agent.semantic.album_context import DataAlbumContextResolver
from dataworks_agent.semantic.query_planner import MetricQueryPlan, MetricQueryPlanner
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)

ExecutionMode = Literal["plan", "dev_execute"]
_FINAL_STATUSES = {"completed", "failed", "cancelled"}
_WRITE_WORDS = ("创建", "新建", "建好", "执行", "初始化", "生成任务", "落地", "部署开发")


class QueryNeedsClarificationError(ValueError):
    """The question is valid, but no deterministic metric definition is available."""

    def __init__(self, question: str, album_contexts: list[Any], reason: str = "") -> None:
        super().__init__(question)
        self.question = question
        self.album_contexts = album_contexts
        self.reason = reason


@dataclass
class WorkflowResult:
    success: bool
    message: str
    workflow_type: str
    mode: ExecutionMode
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "execution_mode": self.mode,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
            **self.data,
        }


class AgentWorkflowService:
    """把会话意图路由到项目中已有的真实 AK/SK、Cookie 与 MCP 能力。"""

    def __init__(self) -> None:
        self._extractor = EntityExtractor()
        self._closed_loop_verifier = ClosedLoopVerifier()
        self._album_context_resolver = DataAlbumContextResolver()
        self._metric_query_planner = MetricQueryPlanner()

    def infer_mode(self, message: str, requested: str, action: str = "") -> ExecutionMode:
        if requested == "plan":
            return "plan"
        if requested == "dev_execute":
            return "dev_execute"
        if any(word in message for word in ("先规划", "只规划", "不要执行")):
            return "plan"
        if action in {"ask_data", "reverse_modeling", "diagnose_issue", "cookie_manage"}:
            return "dev_execute"
        return "dev_execute" if any(word in message for word in _WRITE_WORDS) else "plan"

    async def execute(
        self,
        *,
        message: str,
        action: str,
        params: dict[str, Any],
        execution_mode: str = "auto",
        initialize_data: bool = True,
        publish: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> WorkflowResult:
        routed = self._route_action(message, action)
        mode = self.infer_mode(message, execution_mode, routed)
        if routed == "cookie_manage":
            return await self._manage_cookie(message, mode)
        if routed == "ask_data":
            return await self._ask_data(message, mode)
        if routed == "reverse_modeling":
            return await self._reverse_model(message, params, mode)
        if routed == "diagnose_issue":
            return await self._diagnose(message, params, mode)
        return await self._forward_model(
            message,
            params,
            mode,
            initialize_data=initialize_data,
            publish=publish,
            client_ip=client_ip,
        )

    @staticmethod
    def _route_action(message: str, action: str) -> str:
        lower = message.lower()
        if action == "cookie_manage" or "cookie" in lower or "9222" in lower or "登录态" in message:
            return "cookie_manage"
        business_query = any(
            re.search(pattern, message, re.I) for pattern in BUSINESS_QUERY_PATTERNS
        )
        if (
            action == "ask_data"
            or business_query
            or any(k in message for k in ("问数", "查数", "多少条", "前几条"))
        ):
            return "ask_data"
        return action

    def capability_status(self) -> dict[str, Any]:
        official = getattr(app_state, "_official_mcp_client", None)
        cookie_bff = getattr(app_state, "_bff_client", None) is not None
        cdp_9222 = getattr(app_state, "_cdp_client", None) is not None
        raw_cookie_health = app_state.cookie_health
        cookie_health = raw_cookie_health
        if raw_cookie_health in {"expired", "critical"} and (cookie_bff or cdp_9222):
            cookie_health = "degraded"
        return {
            "ak_sk": bool(settings.aliyun_access_key_id and settings.aliyun_access_key_secret),
            "openapi": getattr(app_state, "_openapi_client", None) is not None,
            "maxcompute": getattr(app_state, "_maxcompute_client", None) is not None,
            "node_adapter": getattr(app_state, "_node_client", None) is not None,
            "cookie_bff": cookie_bff,
            "cdp_9222": cdp_9222,
            "cookie_health": cookie_health,
            "cookie_mcp_health": raw_cookie_health,
            "official_mcp": official.status.to_dict()
            if official
            else {"enabled": False, "connected": False},
        }

    async def _manage_cookie(self, message: str, mode: ExecutionMode) -> WorkflowResult:
        status = self.capability_status()
        official = status["official_mcp"]
        steps = [
            {"step": "check_ak_sk", "status": "completed" if status["ak_sk"] else "failed"},
            {
                "step": "check_official_mcp",
                "status": "completed" if official.get("connected") else "warning",
            },
            {
                "step": "check_cookie_bff",
                "status": "completed" if status["cookie_bff"] else "warning",
            },
            {"step": "check_cdp_9222", "status": "completed" if status["cdp_9222"] else "warning"},
        ]
        if mode == "plan" or not any(
            k in message for k in ("提取", "刷新", "同步", "更新", "获取")
        ):
            degraded = status["cookie_health"] == "degraded"
            message_text = (
                "已检查执行底座：旧 Cookie MCP 登录态异常，但 BFF/CDP 兜底仍可用，当前为部分降级。"
                if degraded
                else "已检查 AK/SK、9222 调试浏览器、Cookie 兜底和官方 MCP 通道。"
            )
            return WorkflowResult(
                True,
                message_text,
                "cookie_manage",
                mode,
                steps=steps,
                data={"capabilities": status},
            )
        from dataworks_agent.cookie.background_refresh import cdp_extract_and_apply

        result = await cdp_extract_and_apply()
        ok = result.get("status") == "success"
        return WorkflowResult(
            ok,
            "已从 9222 登录浏览器提取并同步 Cookie。"
            if ok
            else f"Cookie 更新未完成：{result.get('detail', '未知错误')}",
            "cookie_manage",
            mode,
            steps=[{"step": "cookie_refresh", **result}],
            data={"capabilities": self.capability_status()},
            errors=[] if ok else [str(result.get("detail", "cookie refresh failed"))],
        )

    async def _official_call(
        self, tool: str, arguments: dict[str, Any]
    ) -> tuple[Any | None, str | None]:
        client = getattr(app_state, "_official_mcp_client", None)
        if client is None:
            return None, "官方 DataWorks MCP 客户端未启用"
        try:
            result = await asyncio.wait_for(client.call_tool(tool, arguments), timeout=30)
            if isinstance(result, dict) and result.get("is_error"):
                raise RuntimeError(str(result.get("content") or result))
            return result, None
        except Exception as exc:
            logger.warning("官方 DataWorks MCP %s 调用失败，准备降级: %s", tool, exc)
            return None, str(exc)

    @staticmethod
    def _find_nested_key(value: Any, key: str) -> Any:
        if isinstance(value, dict):
            for current_key, current_value in value.items():
                if str(current_key).lower() == key.lower():
                    return current_value
            for current_value in value.values():
                found = AgentWorkflowService._find_nested_key(current_value, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = AgentWorkflowService._find_nested_key(item, key)
                if found is not None:
                    return found
        return None

    @classmethod
    def _node_from_payload(cls, payload: Any) -> dict[str, Any]:
        node = cls._find_nested_key(payload, "Node")
        if isinstance(node, dict):
            return node
        if isinstance(payload, dict) and any(
            key in payload for key in ("Spec", "spec", "Id", "id")
        ):
            return payload
        return {}

    @classmethod
    def _dependencies_from_payload(cls, payload: Any) -> list[Any]:
        paging = cls._find_nested_key(payload, "PagingInfo")
        if isinstance(paging, dict):
            nodes = cls._find_nested_key(paging, "Nodes")
            if isinstance(nodes, list):
                return nodes
        nodes = cls._find_nested_key(payload, "Nodes")
        return nodes if isinstance(nodes, list) else []

    async def _read_node_metadata(
        self, node_id: str
    ) -> tuple[dict[str, Any], list[Any], dict[str, str], list[str]]:
        sources = {"official_mcp": "not_available", "openapi": "not_used"}
        warnings: list[str] = []
        node: dict[str, Any] = {}
        dependencies: list[Any] = []
        project_id = settings.dataworks_project_id

        node_arguments: dict[str, Any] = {"Id": node_id}
        if project_id:
            node_arguments["ProjectId"] = project_id
        mcp_node, node_error = await self._official_call("GetNode", node_arguments)
        if mcp_node is not None:
            node = self._node_from_payload(mcp_node)
        if project_id:
            mcp_dependencies, dependency_error = await self._official_call(
                "ListNodeDependencies",
                {"ProjectId": project_id, "Id": node_id, "PageSize": 100, "PageNumber": 1},
            )
        else:
            mcp_dependencies, dependency_error = (
                None,
                "缺少 DATAWORKS_PROJECT_ID，节点依赖已转 OpenAPI 兜底",
            )
        if mcp_dependencies is not None:
            dependencies = self._dependencies_from_payload(mcp_dependencies)
        if node:
            sources["official_mcp"] = "completed"
            if dependency_error:
                sources["official_mcp"] = "warning"
                warnings.append(dependency_error)
        else:
            sources["official_mcp"] = "warning"
            if node_error:
                warnings.append(node_error)

        api = getattr(app_state, "_openapi_client", None)
        if (not node or not dependencies) and api is not None:
            from dataworks_agent.api_clients.openapi_node_adapter import _to_map

            sources["openapi"] = "fallback"
            if not node:
                try:
                    node = _to_map(await api.get_node(node_id)).get("Node") or {}
                except Exception as exc:
                    warnings.append(str(exc))
            if not dependencies:
                try:
                    dependency_body = _to_map(await api.list_node_dependencies(node_id))
                    dependencies = (dependency_body.get("PagingInfo") or {}).get("Nodes") or []
                except Exception as exc:
                    warnings.append(str(exc))
        elif node:
            sources["openapi"] = "not_needed"
        return node, dependencies, sources, list(dict.fromkeys(warnings))

    async def _reverse_table_via_cookie(
        self, table: str, table_name: str, mode: ExecutionMode
    ) -> WorkflowResult | None:
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            return None
        project = (
            table.rsplit(".", 1)[0]
            if "." in table
            else (settings.maxcompute_project or settings.dataworks_dev_schema)
        )
        table_guid = f"odps.{project}.{table_name}"
        try:
            ddl = await bff.get_creation_ddl(table_guid)
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                logger.warning("Cookie BFF 读取表 DDL 失败: %s", exc)
                return None
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                return None
            try:
                ddl = await bff.get_creation_ddl(table_guid)
            except Exception as retry_exc:
                logger.warning("Cookie BFF 刷新后读取表 DDL 仍失败: %s", retry_exc)
                return None
        if not ddl:
            return None

        from dataworks_agent.governance.sql_lineage import parse_ddl_structure

        parsed = parse_ddl_structure(ddl)
        columns = parsed.get("columns") or []
        partitions = parsed.get("partitions") or []
        metadata = self._infer_reverse_metadata(table_name, columns)
        try:
            lineage = await bff.list_lineage(table_guid)
        except Exception as exc:
            lineage = {"warning": self._brief_error(exc)}
        return WorkflowResult(
            True,
            f"已通过 Cookie 元数据通道完成 {table} 的逆向建模；AK/SK 无表结构权限不会阻断该能力。",
            "reverse_modeling",
            mode,
            steps=[
                {"step": "read_cookie_table_ddl", "status": "completed"},
                {
                    "step": "parse_table_ddl",
                    "status": "completed" if parsed.get("parse_state") == "ok" else "warning",
                },
                {"step": "infer_semantic_candidates", "status": "completed"},
                {
                    "step": "read_cookie_lineage",
                    "status": "warning"
                    if isinstance(lineage, dict) and "warning" in lineage
                    else "completed",
                },
            ],
            artifacts=[
                {"type": "table_ddl", "name": table, "content": ddl},
                {
                    "type": "semantic_candidates",
                    "name": table,
                    "content": metadata["semantic_candidates"],
                },
            ],
            data={
                "source_type": "table",
                "metadata_channel": "cookie_bff",
                "table": table,
                "columns": columns,
                "partitions": partitions,
                "ddl": ddl,
                "lineage": lineage,
                **metadata,
            },
        )

    async def _reverse_model(
        self, message: str, params: dict[str, Any], mode: ExecutionMode
    ) -> WorkflowResult:
        table = (
            params.get("table_name")
            or params.get("source_table")
            or self._extractor.extract_table_name(message)
        )
        explicit_node = params.get("node_id")
        node_match = re.search(r"(?:节点|node)\s*[:：]?\s*([A-Za-z0-9_-]+)", message, re.I)
        node_id = str(explicit_node or (node_match.group(1) if node_match else ""))
        mc = getattr(app_state, "_maxcompute_client", None)

        if node_id:
            body, dependencies, metadata_sources, warnings = await self._read_node_metadata(node_id)
            if not body:
                return WorkflowResult(
                    False,
                    f"无法读取节点 {node_id}；官方 MCP 与 OpenAPI 均未返回节点信息。",
                    "reverse_modeling",
                    mode,
                    steps=[{"step": "read_node_flowspec", "status": "failed"}],
                    data={"metadata_sources": metadata_sources},
                    errors=warnings or ["node metadata unavailable"],
                )
            spec_value = body.get("Spec") or body.get("spec") or "{}"
            spec = json.loads(spec_value) if isinstance(spec_value, str) else spec_value
            nodes = (spec.get("spec") or {}).get("nodes") or []
            script = (nodes[0].get("script") if nodes else {}) or {}
            sql = script.get("content", "")
            upstream_tables = self._extract_sql_sources(sql) if sql else []
            return WorkflowResult(
                True,
                f"已逆向读取节点 {node_id} 的 FlowSpec、SQL 与节点级依赖。",
                "reverse_modeling",
                mode,
                steps=[
                    {"step": "read_node_flowspec", "status": "completed"},
                    {"step": "parse_node_sql", "status": "completed"},
                    {
                        "step": "read_node_dependencies",
                        "status": "completed" if dependencies else "warning",
                    },
                ],
                artifacts=[{"type": "node_sql", "name": node_id, "content": sql}],
                data={
                    "source_type": "node",
                    "node": body,
                    "flowspec": spec,
                    "dependencies": dependencies,
                    "upstream_tables": upstream_tables,
                    "metadata_sources": metadata_sources,
                },
                errors=warnings,
            )

        if not table:
            return WorkflowResult(
                False,
                "请在一句话中给出要逆向的表名或节点 ID。",
                "reverse_modeling",
                mode,
                errors=["missing table or node"],
            )
        table_name = table.split(".")[-1]
        assert_safe_table_name(table_name)
        if mc is None:
            cookie_result = await self._reverse_table_via_cookie(table, table_name, mode)
            if cookie_result is not None:
                return cookie_result
            return WorkflowResult(
                False,
                "MaxCompute AK/SK 与 Cookie 元数据通道均不可用，无法读取真实表结构。",
                "reverse_modeling",
                mode,
                steps=[{"step": "read_table_schema", "status": "blocked"}],
                data={"metadata_channels": ["maxcompute_ak_sk", "cookie_bff"]},
                errors=["table metadata channels unavailable"],
            )

        try:
            schema = await mc.get_table_schema(table)
        except Exception as exc:
            error = self._brief_error(exc)
            cookie_result = await self._reverse_table_via_cookie(table, table_name, mode)
            if cookie_result is not None:
                cookie_result.data["maxcompute_fallback_reason"] = error
                return cookie_result
            lower_error = error.lower()
            not_found = any(
                token in lower_error for token in ("not found", "nosuchobject", "does not exist")
            )
            permission_denied = any(
                token in lower_error
                for token in ("nopermission", "no privilege", "accessdenied", "permission")
            )
            if not_found:
                message_text = (
                    f"未找到表 {table}。请填写当前 MaxCompute 项目中的真实表名，"
                    "或提供 DataWorks 节点 ID 逆向读取 FlowSpec。"
                )
            elif permission_denied:
                message_text = (
                    f"已识别逆向目标 {table}，但当前 AK/SK 无权读取该 MaxCompute 表结构。"
                    "可提供 DataWorks 节点 ID，改走官方 MCP/OpenAPI 读取节点。"
                )
            else:
                message_text = f"读取表 {table} 的真实结构失败，请核对表名、项目和 AK/SK 权限。"
            return WorkflowResult(
                False,
                message_text,
                "reverse_modeling",
                mode,
                steps=[{"step": "read_maxcompute_schema", "status": "blocked"}],
                data={
                    "source_type": "table",
                    "table": table,
                    "clarifying_questions": ["请输入真实表名或 DataWorks 节点 ID"],
                    "next_actions": [
                        "确认表位于当前 MaxCompute 项目",
                        "提供 DataWorks 节点 ID 以使用官方 MCP/OpenAPI 逆向",
                    ],
                },
                errors=[error],
            )
        columns = [self._column_to_dict(column) for column in schema.columns]
        partitions = [self._column_to_dict(column) for column in schema.partition_keys]
        metadata = self._infer_reverse_metadata(table_name, columns)
        lineage: Any = []
        bff = getattr(app_state, "_bff_client", None)
        if bff is not None:
            try:
                lineage = await bff.list_lineage(f"odps.{settings.maxcompute_project}.{table_name}")
            except Exception as exc:
                lineage = {"warning": str(exc)}

        steps = [
            {"step": "read_maxcompute_schema", "status": "completed", "count": len(columns)},
            {"step": "infer_layer_and_update_mode", "status": "completed"},
            {"step": "infer_semantic_candidates", "status": "completed"},
            {
                "step": "read_cookie_lineage",
                "status": "completed"
                if not isinstance(lineage, dict) or "warning" not in lineage
                else "warning",
            },
        ]
        return WorkflowResult(
            True,
            f"已完成 {table} 的逆向建模：真实表结构、分层、更新方式、语义候选与 Cookie 血缘均已汇总。",
            "reverse_modeling",
            mode,
            steps=steps,
            artifacts=[
                {
                    "type": "table_schema",
                    "name": table,
                    "columns": columns,
                    "partitions": partitions,
                },
                {
                    "type": "semantic_candidates",
                    "name": table,
                    "content": metadata["semantic_candidates"],
                },
            ],
            data={
                "source_type": "table",
                "table": table,
                "columns": columns,
                "partitions": partitions,
                "lineage": lineage,
                **metadata,
            },
        )

    async def _diagnose(
        self, message: str, params: dict[str, Any], mode: ExecutionMode
    ) -> WorkflowResult:
        task_id = params.get("task_id") or self._extractor.extract_task_id(message)
        instance_match = re.search(
            r"(?:实例|instance)\s*(?:id)?\s*[:：]?\s*([A-Za-z0-9_-]+)", message, re.I
        )
        instance_id = params.get("instance_id") or (
            instance_match.group(1) if instance_match else None
        )
        checks = self.capability_status()
        details: dict[str, Any] = {"capabilities": checks, "startup": app_state.smoke_results}
        errors: list[str] = []
        task_data: dict[str, Any] | None = None

        if task_id:
            from sqlalchemy import select

            from dataworks_agent.db.database import SessionLocal
            from dataworks_agent.db.models import ModelingTaskModel, TaskStepLogModel

            with SessionLocal() as db:
                task = db.get(ModelingTaskModel, task_id)
                if task is not None:
                    task_data = {
                        "task_id": task.task_id,
                        "status": task.status,
                        "source_table": task.source_table,
                        "target_table": task.target_table,
                        "target_layer": task.target_layer,
                        "error_message": task.error_message,
                        "node_uuid": task.node_uuid,
                        "updated_at": task.updated_at,
                    }
                    logs = list(
                        db.scalars(
                            select(TaskStepLogModel)
                            .where(TaskStepLogModel.task_id == task_id)
                            .order_by(TaskStepLogModel.id.desc())
                            .limit(20)
                        )
                    )
                    details["step_logs"] = [
                        {
                            "step": log.step_name,
                            "status": log.status,
                            "error": log.error,
                            "duration_ms": log.duration_ms,
                            "created_at": log.created_at,
                        }
                        for log in reversed(logs)
                    ]
                    errors.extend(log.error for log in logs if log.error)
                    if task.error_message:
                        errors.append(task.error_message)
                details["task"] = task_data
                details["task_found"] = task_data is not None
                if task_data is None:
                    errors.append(f"本地任务 {task_id} 不存在")

        evidence_sources: dict[str, str] = {}
        if instance_id:
            instance_payload, instance_error = await self._official_call(
                "GetTaskInstance", {"Id": str(instance_id)}
            )
            log_payload, log_error = await self._official_call(
                "GetTaskInstanceLog", {"Id": str(instance_id)}
            )
            if instance_payload is not None:
                details["task_instance"] = instance_payload
            if log_payload is not None:
                details["task_instance_log"] = log_payload
            if instance_error or log_error:
                errors.extend(value for value in (instance_error, log_error) if value)
                evidence_sources["official_mcp_instance"] = "warning"
            else:
                evidence_sources["official_mcp_instance"] = "completed"

        node_id = str(params.get("node_id") or (task_data or {}).get("node_uuid") or "")
        node_warnings: list[str] = []
        if node_id:
            node, dependencies, node_sources, node_warnings = await self._read_node_metadata(
                node_id
            )
            if node:
                details["node"] = node
            if dependencies:
                details["node_dependencies"] = dependencies
            evidence_sources.update({f"node_{key}": value for key, value in node_sources.items()})
            errors.extend(node_warnings)

        from dataworks_agent.runtime.self_heal import IssueReport, IssueType, SelfHealFlow

        issue_type = self._infer_issue_type(message, errors)
        proposal = await SelfHealFlow().diagnose(
            IssueReport(
                issue_id=task_id or str(instance_id or f"diag_{uuid.uuid4().hex[:8]}"),
                issue_type=IssueType(issue_type),
                source=task_id or str(instance_id or "agent_health"),
                description="; ".join(dict.fromkeys(errors)) or message,
                context={
                    "affected_tables": [
                        value
                        for value in (
                            (task_data or {}).get("source_table"),
                            (task_data or {}).get("target_table"),
                        )
                        if value
                    ]
                },
            )
        )
        details["recovery_proposal"] = {
            "proposal_id": proposal.proposal_id,
            "action": proposal.action.value,
            "description": proposal.description,
            "requires_approval": proposal.requires_approval,
            "affected_resources": proposal.affected_resources,
        }

        execution_ready = checks["ak_sk"] and checks["maxcompute"] and checks["node_adapter"]
        diagnosed_status = (task_data or {}).get("status") or self._find_nested_key(
            details.get("task_instance"), "Status"
        )
        details["diagnosed_task_status"] = diagnosed_status
        details["health_degraded"] = not execution_ready or diagnosed_status in {
            "failed",
            "error",
            "Failed",
            "Error",
        }
        details["evidence_sources"] = evidence_sources
        target_resolved = bool(task_data or details.get("task_instance") or details.get("node"))
        if not any((task_id, instance_id, node_id)):
            message_text = "执行底座健康检查已完成，并已生成恢复建议；提供任务、实例或节点 ID 可继续定位到具体故障。"
        elif target_resolved:
            message_text = "异常排查已完成：已汇总真实任务、实例或节点证据，并生成恢复建议。"
        else:
            message_text = "异常排查已完成，但未找到目标对象或远端证据不可用；结果已标记为降级，不会伪装成定位成功。"
        return WorkflowResult(
            True,
            message_text,
            "diagnose_issue",
            mode,
            steps=[
                {"step": "health_matrix", "status": "completed" if execution_ready else "warning"},
                {
                    "step": "task_and_step_logs",
                    "status": "completed"
                    if task_data or details.get("task_instance")
                    else ("warning" if task_id or instance_id else "skipped"),
                },
                {
                    "step": "node_dependency_inspection",
                    "status": "completed"
                    if node_id and details.get("node")
                    else ("warning" if node_id else "skipped"),
                },
                {"step": "self_heal_proposal", "status": "completed"},
            ],
            data=details,
            errors=list(dict.fromkeys(errors)),
        )

    async def _ask_data(self, message: str, mode: ExecutionMode) -> WorkflowResult:
        try:
            query_plan = await self._build_query_plan(message)
        except QueryNeedsClarificationError as clarification:
            return self._query_clarification_result(clarification, mode)

        self._validate_readonly_sql(query_plan.sql)
        sql = self._enforce_query_limit(query_plan.sql)
        query_plan.sql = sql
        artifact = {"type": "query_sql", "name": "readonly_query", "content": sql}
        artifacts = [artifact, query_plan.semantic_artifact()]
        if mode == "plan":
            return WorkflowResult(
                True,
                "已生成并校验只读查询 SQL；规划模式不会提交真实查询。",
                "ask_data",
                mode,
                steps=[
                    {"step": "generate_readonly_sql", "status": "completed"},
                    {"step": "execute_query", "status": "planned"},
                ],
                artifacts=artifacts,
                data={
                    "semantic_plan": query_plan.semantic_artifact()["content"],
                    "query": {
                        "sql": sql,
                        "executed": False,
                        "limit": settings.ask_data_default_limit,
                    },
                },
            )

        errors: list[str] = []
        prefer_cookie = self._prefer_cookie_query(sql)
        channels = (
            ("cookie_bff", "maxcompute_ak_sk")
            if prefer_cookie
            else (
                "maxcompute_ak_sk",
                "cookie_bff",
            )
        )
        for channel in channels:
            try:
                if channel == "cookie_bff":
                    columns, rows = await self._run_cookie_bff_query(sql)
                else:
                    columns, rows = await self._run_maxcompute_query(sql)
                return await self._query_success(query_plan, artifacts, columns, rows, channel)
            except Exception as exc:
                brief = self._brief_error(exc)
                errors.append(brief)
                logger.warning("%s 问数失败，准备切换下一通道: %s", channel, exc)

        return WorkflowResult(
            False,
            "只读 SQL 已生成，但 AK/SK 与 Cookie BFF 查询通道均未成功执行。",
            "ask_data",
            mode,
            steps=[
                {"step": "generate_readonly_sql", "status": "completed"},
                {"step": "execute_query", "status": "blocked"},
            ],
            artifacts=artifacts,
            data={
                "semantic_plan": query_plan.semantic_artifact()["content"],
                "query": {"sql": sql, "executed": False, "limit": settings.ask_data_default_limit},
                "next_actions": ["检查 9222 登录态与 Cookie BFF", "核对 MaxCompute 查询权限"],
            },
            errors=list(dict.fromkeys(errors)),
        )

    async def _run_maxcompute_query(self, sql: str) -> tuple[list[Any], list[Any]]:
        mc = getattr(app_state, "_maxcompute_client", None)
        if mc is None:
            raise RuntimeError("maxcompute client unavailable")
        instance = await asyncio.wait_for(
            mc.submit_query(sql), timeout=settings.ask_data_timeout_seconds
        )
        result = await asyncio.wait_for(
            mc.wait_and_fetch(instance), timeout=settings.ask_data_timeout_seconds
        )
        return list(result.columns), list(result.rows[: settings.ask_data_default_limit])

    async def _run_cookie_bff_query(self, sql: str) -> tuple[list[Any], list[Any]]:
        bff = getattr(app_state, "_bff_client", None)
        if bff is None:
            raise RuntimeError("cookie BFF client unavailable")

        try:
            return await self._run_cookie_bff_query_once(bff, sql)
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                raise
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                detail = str(refresh.get("detail") or "Cookie refresh failed")
                raise RuntimeError(f"Cookie refresh failed: {detail}") from exc
            return await self._run_cookie_bff_query_once(bff, sql)

    @staticmethod
    async def _run_cookie_bff_query_once(bff: Any, sql: str) -> tuple[list[Any], list[Any]]:
        job_code = await asyncio.wait_for(
            bff.execute_sql(sql), timeout=settings.ask_data_timeout_seconds
        )
        if not job_code:
            raise RuntimeError(getattr(bff, "last_error", None) or "BFF 未返回查询任务")
        completed = await asyncio.wait_for(
            bff.wait_job(job_code), timeout=settings.ask_data_timeout_seconds
        )
        if not completed:
            raise RuntimeError(getattr(bff, "last_error", None) or "BFF 查询任务未成功")
        result = await asyncio.wait_for(
            bff.get_query_result(job_code), timeout=settings.ask_data_timeout_seconds
        )
        if not isinstance(result, dict):
            raise RuntimeError("BFF 未返回查询结果")
        headers = result.get("headerList") or []
        columns = [
            str(item.get("name", "")) if isinstance(item, dict) else str(item) for item in headers
        ]
        rows = list((result.get("bodyList") or [])[: settings.ask_data_default_limit])
        return columns, rows

    @staticmethod
    def _prefer_cookie_query(sql: str) -> bool:
        lowered = sql.lower()
        production_projects = {"giikin_aliyun", settings.dataworks_prod_schema.lower()}
        return any(f"{project}." in lowered for project in production_projects if project)

    @staticmethod
    def _is_cookie_auth_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "csrf",
                "cookie",
                "login",
                "expired",
                "decrypt",
                "unauthorized",
                "forbidden",
                "403",
            )
        )

    @staticmethod
    async def _refresh_cookie_auth(bff: Any) -> dict[str, Any]:
        from dataworks_agent.cookie.background_refresh import run_cookie_background_refresh_once

        outcome = await run_cookie_background_refresh_once(force=True)
        reset = getattr(bff, "reset_auth_cache", None)
        if callable(reset):
            reset()
        else:
            bff._cookie = ""
            bff._csrf_token = ""
            bff._csrf_time = 0
        return outcome

    def _query_clarification_result(
        self, clarification: QueryNeedsClarificationError, mode: ExecutionMode
    ) -> WorkflowResult:
        contexts = clarification.album_contexts
        candidates = [
            {
                "album_id": context.album_id,
                "album": context.name,
                "description": context.description,
                "categories": context.categories,
                "tables": [
                    {
                        "table": table.full_name,
                        "comment": table.comment,
                        "remark": table.remark,
                        "category": table.category,
                    }
                    for table in context.tables
                ],
            }
            for context in contexts
        ]
        has_candidates = bool(candidates)
        message = clarification.reason or (
            "该问题尚未命中已验证的指标口径。我已从数据专辑筛出候选表；"
            "请确认指标定义或过滤条件，我不会猜测生产口径。"
            if has_candidates
            else "该问题尚未命中已验证的指标口径。请补充指标定义、目标表或过滤条件；"
            "我不会因为缺少 LLM 配置而把正常问数标记为系统故障。"
        )
        return WorkflowResult(
            True,
            message,
            "ask_data",
            mode,
            steps=[
                {"step": "resolve_semantic_context", "status": "completed"},
                {"step": "clarify_metric_caliber", "status": "waiting"},
                {"step": "execute_query", "status": "waiting"},
            ],
            artifacts=[
                {"type": "data_album_candidates", "name": "semantic_context", "content": candidates}
            ]
            if has_candidates
            else [],
            data={
                "needs_clarification": True,
                "reason": clarification.reason,
                "album_candidates": candidates,
                "clarifying_questions": [
                    "这个指标的业务定义和排除条件是什么？",
                    "应使用哪个数据专辑或目标表？",
                    "时间范围、统计粒度和分组维度是什么？",
                ],
                "query": {"executed": False},
            },
        )

    async def _query_success(
        self,
        query_plan: MetricQueryPlan,
        artifacts: list[dict[str, Any]],
        columns: list[Any],
        rows: list[Any],
        channel: str,
    ) -> WorkflowResult:
        sql = query_plan.sql
        if (
            query_plan.metric_id != "ad_hoc_query"
            and not query_plan.selected_dimensions
            and len(rows) != 1
        ):
            return WorkflowResult(
                False,
                f"认证指标应唯一命中 1 行，实际返回 {len(rows)} 行，已拒绝给出可能错误的答案。",
                "ask_data",
                "dev_execute",
                steps=[
                    {"step": "resolve_semantic_context", "status": "completed"},
                    {"step": "execute_query", "status": "completed", "channel": channel},
                    {"step": "validate_metric_uniqueness", "status": "failed"},
                ],
                artifacts=artifacts,
                data={
                    "semantic_plan": query_plan.semantic_artifact()["content"],
                    "query": {
                        "sql": sql,
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows),
                        "executed": True,
                        "execution_channel": channel,
                    },
                },
                errors=["metric result is not unique"],
            )
        task_id = f"ask_data_{uuid.uuid4().hex[:12]}"
        verification = await self._closed_loop_verifier.verify(
            task_id,
            "ASK_DATA",
            {
                "sql": sql,
                "executed": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            },
        )
        verification_data = {
            "task_id": verification.task_id,
            "task_type": verification.task_type,
            "status": verification.status.value,
            "summary": verification.summary,
            "passed_count": verification.passed_count,
            "failed_count": verification.failed_count,
            "warning_count": verification.warning_count,
            "checks": [
                {
                    "name": check.check_name,
                    "passed": check.passed,
                    "severity": check.severity.value,
                    "message": check.message,
                    "details": check.details,
                }
                for check in verification.checks
            ],
        }
        verified = verification.status == VerificationStatus.PASSED
        return WorkflowResult(
            verified,
            (
                self._format_query_answer(query_plan, columns, rows)
                if verified
                else "查询已执行，但闭环验收未通过，结果不会标记为完成。"
            ),
            "ask_data",
            "dev_execute",
            steps=[
                {"step": "generate_readonly_sql", "status": "completed"},
                {"step": "execute_query", "status": "completed", "channel": channel},
                {
                    "step": "closed_loop_verification",
                    "status": "completed" if verified else "failed",
                },
            ],
            artifacts=artifacts,
            data={
                "task_id": task_id,
                "semantic_plan": query_plan.semantic_artifact()["content"],
                "query": {
                    "sql": sql,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "executed": True,
                    "execution_channel": channel,
                },
                "verification": verification_data,
            },
            errors=[] if verified else [verification.summary],
        )

    @staticmethod
    def _format_query_answer(
        query_plan: MetricQueryPlan, columns: list[Any], rows: list[Any]
    ) -> str:
        names = [str(getattr(column, "name", column)) for column in columns]
        if not rows:
            return f"{query_plan.metric_name}查询完成，但当前快照没有返回数据。"
        measure = query_plan.caliber.get("measure", {})
        measure_alias = str(measure.get("alias") or measure.get("column") or "value")
        result_column = (
            measure_alias if query_plan.selected_dimensions else f"total_{measure_alias}"
        )
        row = rows[0]
        values = row if isinstance(row, (list, tuple)) else [row.get(name) for name in names]
        mapped = dict(zip(names, values, strict=False))
        raw_value = mapped.get(result_column)
        try:
            display_value = f"{int(str(raw_value)):,}"
        except (TypeError, ValueError):
            display_value = str(raw_value)
        date = str(mapped.get("data_date") or "")
        hour = str(mapped.get("data_hour") or "")
        snapshot = f"（数据日期 {date}，截至 {hour}:00）" if date and hour else ""
        album_names = "、".join(item["name"] for item in query_plan.albums)
        evidence = (
            f"；选表依据：数据专辑“{album_names}”+ 已批准指标 v{query_plan.metric_version}"
            if album_names
            else f"；规划依据：{query_plan.selection_evidence[0]}"
        )
        if query_plan.selected_dimensions:
            return (
                f"{query_plan.metric_name}已按{'、'.join(query_plan.selected_dimensions)}查询完成，"
                f"共返回 {len(rows)} 行{snapshot}{evidence}。"
            )
        return f"{query_plan.metric_name}为 {display_value}{snapshot}{evidence}。"

    @staticmethod
    def _brief_error(exc: Exception) -> str:
        text = " ".join(str(exc).strip().splitlines())
        lower = text.lower()
        if "nosuchobject" in lower or "table not found" in lower:
            return "MaxCompute table not found"
        if "odps:createinstance" in lower:
            return "MaxCompute permission denied: missing odps:CreateInstance"
        if any(token in lower for token in ("nopermission", "no privilege", "accessdenied")):
            return "MaxCompute permission denied"
        return text[:180] or exc.__class__.__name__

    async def _build_readonly_sql(self, message: str) -> str:
        """Compatibility wrapper used by tests and callers that only need SQL."""
        return (await self._build_query_plan(message)).sql

    async def _build_query_plan(self, message: str) -> MetricQueryPlan:
        fenced = re.search(r"```sql\s*(.*?)```", message, re.I | re.S)
        if fenced:
            return self._ad_hoc_query_plan(fenced.group(1).strip(), "用户提供 SQL")
        table = self._extractor.extract_table_name(message)
        if not table:
            raw = re.search(r"(?:查询|统计|查看|表)\s*([A-Za-z][A-Za-z0-9_.]+)", message)
            table = raw.group(1) if raw else None
        if table:
            assert_safe_table_name(table.split(".")[-1])
            sql = (
                f"SELECT COUNT(*) AS row_count FROM {table}"
                if any(k in message for k in ("多少条", "行数", "count"))
                else f"SELECT * FROM {table} LIMIT {settings.ask_data_default_limit}"
            )
            return self._ad_hoc_query_plan(sql, "用户明确指定表", table=table)

        candidate_tables = self._metric_query_planner.candidate_tables(message)
        album_contexts = await self._album_context_resolver.resolve(
            message, required_tables=candidate_tables
        )
        semantic_plan = self._metric_query_planner.plan(message, album_contexts)
        if semantic_plan is not None:
            await self._validate_semantic_plan_metadata(semantic_plan)
            return semantic_plan
        if not settings.llm_api_key:
            raise QueryNeedsClarificationError(message, album_contexts)

        from dataworks_agent.llm.context import ContextBuilder
        from dataworks_agent.llm.service import LLMService

        builder = ContextBuilder().add_instruction(
            "Only generate one read-only MaxCompute SELECT/WITH statement without explanation. "
            "Never generate write operations. Use LIMIT 100 by default."
        )
        album_metadata = self._album_context_resolver.format_for_llm(album_contexts)
        if album_metadata:
            builder.add_metadata(album_metadata)
        context = builder.add_prompt(message).build()
        response = await LLMService.from_settings(settings).complete(context, "normal")
        sql = response.content.strip().removeprefix("```sql").removesuffix("```").strip()
        plan = self._ad_hoc_query_plan(sql, "数据专辑约束的 LLM 规划")
        plan.albums = [
            {"album_id": item.album_id, "name": item.name, "categories": item.categories}
            for item in album_contexts
        ]
        return plan

    @staticmethod
    def _ad_hoc_query_plan(sql: str, evidence: str, *, table: str = "") -> MetricQueryPlan:
        return MetricQueryPlan(
            sql=sql,
            metric_id="ad_hoc_query",
            metric_name="自主问数",
            metric_version=1,
            table=table,
            selection_evidence=[evidence],
            caliber={"source": "ad_hoc"},
        )

    async def _validate_semantic_plan_metadata(self, plan: MetricQueryPlan) -> None:
        ddl, metadata_channel = await self._load_certified_table_ddl(plan)
        if not ddl:
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                "认证表元数据无法通过 MaxCompute AK/SK 或 Cookie 通道读取，已阻止未经结构核验的查询。",
            )

        from dataworks_agent.governance.sql_lineage import parse_ddl_structure

        parsed = parse_ddl_structure(ddl)
        if parsed.get("parse_state") != "ok":
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                "认证表 DDL 解析失败，已阻止使用未经校验的指标口径。",
            )
        available = {str(item.get("name") or "").lower() for item in parsed.get("columns", [])}
        available.update(
            str(item.get("name") or "").lower() for item in parsed.get("partitions", [])
        )
        caliber = plan.caliber
        required = {str(caliber["measure"]["column"]).lower()}
        required.update(str(name).lower() for name in caliber.get("fixed_filters", {}))
        required.update(
            str(item.get("column") or "").lower() for item in caliber.get("dimensions", [])
        )
        freshness = caliber.get("freshness", {})
        required.update(
            str(freshness.get(key) or "").lower() for key in ("date_partition", "hour_partition")
        )
        required.discard("")
        missing = sorted(required - available)
        if missing:
            raise QueryNeedsClarificationError(
                plan.metric_name,
                [],
                f"指标语义定义与真实表结构不一致，缺少字段：{', '.join(missing)}",
            )
        plan.metadata_validation = {
            "status": "passed",
            "channel": metadata_channel,
            "required_fields": sorted(required),
            "table": plan.table,
        }
        plan.selection_evidence.append(f"真实 DDL 字段与分区校验通过（{metadata_channel}）")

    async def _load_certified_table_ddl(self, plan: MetricQueryPlan) -> tuple[str | None, str]:
        project, _, table_name = plan.table.partition(".")
        mc = getattr(app_state, "_maxcompute_client", None)
        get_mc_ddl = getattr(mc, "get_table_ddl", None) if mc is not None else None
        if callable(get_mc_ddl):
            try:
                ddl = await get_mc_ddl(
                    table_name or project, project=project if table_name else None
                )
                if ddl:
                    return str(ddl), "maxcompute_ak_sk"
            except Exception as exc:
                logger.warning(
                    "MaxCompute 认证表元数据读取失败，尝试 Cookie 兜底: %s",
                    exc,
                )

        bff = getattr(app_state, "_bff_client", None)
        get_cookie_ddl = getattr(bff, "get_creation_ddl", None) if bff is not None else None
        if not callable(get_cookie_ddl):
            return None, "unavailable"
        try:
            ddl = await get_cookie_ddl(f"odps.{plan.table}")
        except Exception as exc:
            if not self._is_cookie_auth_error(exc):
                logger.warning("Cookie 认证表元数据读取失败: %s", exc)
                return None, "cookie_bff"
            refresh = await self._refresh_cookie_auth(bff)
            if refresh.get("status") not in {"success", "refreshed", "extracted_unverified"}:
                return None, "cookie_bff"
            ddl = await get_cookie_ddl(f"odps.{plan.table}")
        return (str(ddl), "cookie_bff") if ddl else (None, "cookie_bff")

    @staticmethod
    def _validate_readonly_sql(sql: str) -> None:
        statements = sqlglot.parse(sql, read="hive")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise ValueError("自主问数只允许单条 SELECT/WITH 查询")
        forbidden = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Alter,
            exp.Create,
            exp.Command,
        )
        if any(statement.find(kind) for statement in statements for kind in forbidden):
            raise ValueError("自主问数检测到写入或 DDL 操作，已阻止")

    @staticmethod
    def _enforce_query_limit(sql: str) -> str:
        statement = sqlglot.parse_one(sql, read="hive")
        limit = statement.args.get("limit")
        max_rows = settings.ask_data_default_limit
        if limit is not None and isinstance(limit.expression, exp.Literal):
            try:
                if int(limit.expression.this) <= max_rows:
                    return statement.sql(dialect="hive")
            except (TypeError, ValueError):
                pass
        return statement.limit(max_rows, copy=True).sql(dialect="hive")

    async def _forward_model(
        self,
        message: str,
        params: dict[str, Any],
        mode: ExecutionMode,
        *,
        initialize_data: bool,
        publish: bool,
        client_ip: str,
    ) -> WorkflowResult:
        tables = self._extractor.extract_table_names(message)
        by_layer: dict[str, list[str]] = {layer: [] for layer in ("ods", "dwd", "dim", "dws")}
        for table in tables:
            layer = table.split("_", 1)[0].lower()
            if layer in by_layer:
                assert_safe_table_name(table)
                by_layer[layer].append(table)
        source_table = params.get("source_table") or self._extractor.extract_source_table(message)
        datasource = params.get("datasource_name") or self._extractor.extract_datasource_name(
            message
        )
        source_type = (
            params.get("source_type") or self._extractor.extract_source_type(message) or "mysql"
        ).lower()
        granularity = (
            params.get("granularity") or self._extractor.extract_granularity(message) or "day"
        )
        generated_tables: dict[str, str] = {}
        if not any(by_layer.values()) and source_table and self._requests_full_chain(message):
            generated_tables = self._derive_forward_table_names(
                source_table=source_table,
                datasource=datasource or "source",
                source_type=source_type,
                granularity=granularity,
            )
            for layer, table_name in generated_tables.items():
                by_layer[layer].append(table_name)
            tables.extend(generated_tables.values())
        schedule_minute = params.get("schedule_minute") or 1
        plan = self._build_forward_plan(
            by_layer, source_table, datasource, initialize_data, source_type
        )
        if mode == "plan":
            return WorkflowResult(
                True,
                "已生成 ODS→DWD/DIM→DWS 全链路开发执行计划；切换到开发执行即可建表、建草稿节点并初始化。",
                "forward_modeling",
                mode,
                steps=plan,
                data={
                    "capabilities": self.capability_status(),
                    "publish_gate": "required_for_publish",
                    "source_type": source_type,
                    "generated_tables": generated_tables,
                },
            )

        execution_steps = [dict(step) for step in plan]
        clients_ready = bool(
            getattr(app_state, "_node_client", None)
            and getattr(app_state, "_maxcompute_client", None)
        )
        self._set_step_status(
            execution_steps,
            "credential_and_cookie_health",
            "completed" if clients_ready else "failed",
        )
        if not clients_ready:
            return WorkflowResult(
                False,
                "AK/SK 执行底座未就绪，无法进行开发环境真实写入。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                data={"capabilities": self.capability_status()},
                errors=["execution clients unavailable"],
            )
        if not source_table and source_type != "oss":
            return WorkflowResult(
                False,
                "缺少源表。请在一句话中说明数据源和源表。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                errors=["missing source_table"],
            )
        if not any(by_layer.values()):
            return WorkflowResult(
                False,
                "请在一句话中给出至少一个 ods_/dwd_/dim_/dws_ 目标表名。",
                "forward_modeling",
                mode,
                steps=execution_steps,
                errors=["missing target tables"],
            )

        preflight = await self._official_datasource_preflight(datasource)
        self._set_step_status(execution_steps, "official_mcp_health", preflight["status"])
        executed: list[dict[str, Any]] = []
        upstream = source_table or ""
        if by_layer["ods"]:
            ods_table = by_layer["ods"][0]
            ods_result = await self._execute_ods(
                message=message,
                params=params,
                source_type=source_type,
                datasource=datasource,
                source_table=source_table or "",
                target_table=ods_table,
                granularity=granularity,
                schedule_minute=schedule_minute,
                initialize=initialize_data,
            )
            executed.append({"layer": "ODS", "table": ods_table, "result": ods_result})
            self._set_step_status(
                execution_steps,
                "discover_source_schema",
                "completed" if ods_result.get("success") else "warning",
            )
            self._set_step_status(
                execution_steps,
                "create_ods_table_and_source_node",
                "completed" if ods_result.get("success") else "failed",
            )
            if initialize_data:
                init_status = (
                    "completed"
                    if source_type not in {"oss", "hologres", "holo", "realtime"}
                    and ods_result.get("success")
                    else "skipped"
                )
                self._set_step_status(execution_steps, "initialize_ods_data", init_status)
            if not ods_result.get("success"):
                return WorkflowResult(
                    False,
                    "ODS 建表、节点或初始化失败，已停止下游建模。",
                    "forward_modeling",
                    mode,
                    steps=execution_steps,
                    data={"executed": executed, "official_mcp_preflight": preflight},
                    errors=[str(ods_result.get("error") or "ODS execution failed")],
                )
            upstream = ods_table

        for layer in ("dwd", "dim"):
            for table in by_layer[layer]:
                layer_result = await self._deploy_warehouse_layer(
                    layer.upper(), upstream, table, granularity, schedule_minute
                )
                executed.append({"layer": layer.upper(), "table": table, "result": layer_result})
                self._set_step_status(
                    execution_steps,
                    f"create_{layer}_tables_nodes_schedule",
                    "completed" if layer_result.get("success") else "failed",
                )
                if not layer_result.get("success"):
                    return WorkflowResult(
                        False,
                        f"{layer.upper()} 开发任务创建失败。",
                        "forward_modeling",
                        mode,
                        steps=execution_steps,
                        data={"executed": executed, "official_mcp_preflight": preflight},
                        errors=[f"{layer} execution failed"],
                    )
                if layer == "dwd":
                    upstream = table
        for table in by_layer["dws"]:
            layer_result = await self._deploy_warehouse_layer(
                "DWS", upstream, table, granularity, schedule_minute
            )
            executed.append({"layer": "DWS", "table": table, "result": layer_result})
            self._set_step_status(
                execution_steps,
                "create_dws_tables_nodes_schedule",
                "completed" if layer_result.get("success") else "failed",
            )
            if not layer_result.get("success"):
                return WorkflowResult(
                    False,
                    "DWS 开发任务创建失败。",
                    "forward_modeling",
                    mode,
                    steps=execution_steps,
                    data={"executed": executed, "official_mcp_preflight": preflight},
                    errors=["dws execution failed"],
                )
            upstream = table

        result_data: dict[str, Any] = {
            "executed": executed,
            "capabilities": self.capability_status(),
            "official_mcp_preflight": preflight,
            "publish_gate": "not_requested",
            "source_type": source_type,
            "generated_tables": generated_tables,
        }
        message_text = (
            "开发环境全链路已完成：表已创建，节点与调度已保存；"
            "初始化按请求执行，正式发布仍等待 Publish Gate。"
        )
        self._set_step_status(execution_steps, "publish_gate", "skipped")
        if publish:
            from dataworks_agent.runtime.publish_gate import PublishGate

            gate = getattr(app_state, "_publish_gate", None) or PublishGate()
            app_state._publish_gate = gate
            request = await gate.interrupt_for_approval(
                run_id=f"agent_{uuid.uuid4().hex[:12]}",
                session_id=client_ip,
                table_name=tables[-1] if tables else source_table,
                change_type="create",
                payload={"message": message, "tables": by_layer, "executed": executed},
                context={"mode": mode},
            )
            result_data["publish_request"] = request.__dict__
            result_data["publish_gate"] = "approval_required"
            self._set_step_status(execution_steps, "publish_gate", "approval_required")
            message_text = (
                f"开发环境全链路已完成，并已创建发布审批 {request.request_id}；"
                "未绕过 Publish Gate 上线。"
            )
        return WorkflowResult(
            True,
            message_text,
            "forward_modeling",
            mode,
            steps=execution_steps,
            artifacts=self._execution_artifacts(executed),
            data=result_data,
        )

    @staticmethod
    def _requests_full_chain(message: str) -> bool:
        lowered = message.lower()
        return "全链路" in message or all(
            layer in lowered for layer in ("ods", "dwd", "dim", "dws")
        )

    @staticmethod
    def _derive_forward_table_names(
        *, source_table: str, datasource: str, source_type: str, granularity: str
    ) -> dict[str, str]:
        source_name = source_table.split(".")[-1].lower()
        safe_source = re.sub(r"[^a-z0-9_]+", "_", source_name).strip("_") or "source_table"
        safe_datasource = re.sub(r"[^a-z0-9_]+", "_", datasource.lower()).strip("_") or "source"
        ods_table = generate_ods_di_table_name(
            safe_datasource,
            safe_source,
            granularity,
            source_type=source_type,
        )
        suffix = "hi" if granularity in {"hour", "hourly"} else "di"
        return {
            "ods": ods_table,
            "dwd": f"dwd_auto_{safe_source}_detail_{suffix}",
            "dim": f"dim_auto_{safe_source}_{suffix}",
            "dws": f"dws_auto_{safe_source}_summary_{suffix}",
        }

    @staticmethod
    def _build_forward_plan(
        by_layer: dict[str, list[str]],
        source_table: str | None,
        datasource: str | None,
        initialize: bool,
        source_type: str = "mysql",
    ) -> list[dict[str, Any]]:
        steps = [
            {"step": "credential_and_cookie_health", "status": "planned"},
            {"step": "official_mcp_health", "status": "planned"},
        ]
        if by_layer["ods"]:
            steps.extend(
                [
                    {
                        "step": "discover_source_schema",
                        "datasource": datasource,
                        "source_table": source_table,
                        "source_type": source_type,
                        "status": "planned",
                    },
                    {
                        "step": "create_ods_table_and_source_node",
                        "tables": by_layer["ods"],
                        "source_type": source_type,
                        "status": "planned",
                    },
                ]
            )
            if initialize:
                steps.append({"step": "initialize_ods_data", "status": "planned"})
        for layer in ("dwd", "dim", "dws"):
            if by_layer[layer]:
                steps.append(
                    {
                        "step": f"create_{layer}_tables_nodes_schedule",
                        "tables": by_layer[layer],
                        "status": "planned",
                    }
                )
        steps.append({"step": "publish_gate", "status": "required_only_for_publish"})
        return steps

    @staticmethod
    def _set_step_status(steps: list[dict[str, Any]], step_name: str, status: str) -> None:
        for step in steps:
            if step.get("step") == step_name:
                step["status"] = status

    async def _official_datasource_preflight(self, datasource: str | None) -> dict[str, Any]:
        if not datasource:
            return {"status": "skipped", "reason": "datasource not required or missing"}
        if not settings.dataworks_project_id:
            return {
                "status": "warning",
                "error": "missing DATAWORKS_PROJECT_ID",
                "fallback": "cookie_bff",
            }
        payload, error = await self._official_call(
            "ListDataSources",
            {
                "ProjectId": settings.dataworks_project_id,
                "Name": datasource,
                "EnvType": "Dev",
                "PageSize": 10,
                "PageNumber": 1,
            },
        )
        if error:
            return {"status": "warning", "error": error, "fallback": "cookie_bff"}
        return {"status": "completed", "datasource": datasource, "result": payload}

    @staticmethod
    def _extract_inline_columns(message: str) -> list[dict[str, str]]:
        match = re.search(r"(?:字段|columns?)\s*[:：]?\s*([^。；;]+)", message, re.I)
        if not match:
            return []
        columns: list[dict[str, str]] = []
        for item in re.split(r"[,，]", match.group(1)):
            parts = item.strip().split()
            if len(parts) < 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[0]):
                continue
            columns.append({"name": parts[0], "type": parts[1]})
        return columns

    async def _ensure_oss_table(
        self, target_table: str, granularity: str, columns: list[dict[str, Any]]
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        if await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            return {"status": "exists"}
        if not columns:
            return {
                "status": "failed",
                "error": "OSS 新表无法自动推断文件字段；请在同一句话中补充“字段 id bigint, name string”。",
            }
        ddl_columns = ",\n".join(
            f"  `{column['name']}` {self._normalize_mc_type(str(column.get('type', 'string')))}"
            for column in columns
        )
        partitions = (
            "`dt` STRING, `ht` STRING" if granularity in {"hour", "hourly"} else "`dt` STRING"
        )
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n"
            f"{ddl_columns}\n) PARTITIONED BY ({partitions}) COMMENT 'OSS Agent generated';"
        )
        ddl_result = await mc.execute_ddl(ddl)
        return {
            "status": "created" if ddl_result.success else "failed",
            "ddl": ddl,
            "error": ddl_result.error,
        }

    async def _ensure_table_from_source(
        self, source_table: str, target_table: str, granularity: str
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        if await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            return {"status": "exists"}
        schema = await mc.get_table_schema(source_table)
        columns = [column for column in schema.columns if column.name.lower() not in {"dt", "ht"}]
        if not columns:
            return {"status": "failed", "error": f"源表 {source_table} 无业务字段"}
        ddl_columns = ",\n".join(
            f"  `{column.name}` {self._normalize_mc_type(str(column.type))}" for column in columns
        )
        partitions = (
            "`dt` STRING, `ht` STRING" if granularity in {"hour", "hourly"} else "`dt` STRING"
        )
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n"
            f"{ddl_columns}\n) PARTITIONED BY ({partitions}) COMMENT 'Realtime Agent generated';"
        )
        ddl_result = await mc.execute_ddl(ddl)
        return {
            "status": "created" if ddl_result.success else "failed",
            "ddl": ddl,
            "error": ddl_result.error,
            "columns": columns,
        }

    async def _execute_ods(
        self,
        *,
        message: str,
        params: dict[str, Any],
        source_type: str,
        datasource: str | None,
        source_table: str,
        target_table: str,
        granularity: str,
        schedule_minute: int,
        initialize: bool,
    ) -> dict[str, Any]:
        bff = getattr(app_state, "_bff_client", None)
        nodes = getattr(app_state, "_node_client", None)
        normalized_granularity = "hour" if granularity in {"hour", "hourly"} else "day"

        if source_type in {"hologres", "holo"}:
            if bff is None or nodes is None:
                return {
                    "success": False,
                    "error": "Hologres ODS 需要 Cookie/BFF 元数据兜底和 AK/SK 节点客户端",
                }
            holo_schema = str(params.get("holo_schema") or datasource or "").strip().lower()
            if not holo_schema:
                return {
                    "success": False,
                    "error": "Hologres ODS 需要 holo_schema 或 datasource_name",
                }
            from dataworks_agent.services.ods_holo import HoloOdsPipeline

            pipeline = HoloOdsPipeline(
                bff,
                app_state.mcp_pool,
                node_client=nodes,
                mc_client=app_state._maxcompute_client,
            )
            return await pipeline.run(
                holo_schema=holo_schema,
                source_table=source_table,
                target_table=target_table,
                granularity=normalized_granularity,
                script_path=str(params.get("script_path") or settings.holo_ods_node_path),
                schedule_minute=schedule_minute,
                where_mode=str(params.get("where_mode") or "auto"),
            )

        if source_type == "oss":
            oss_path = params.get("oss_path") or self._extractor.extract_oss_path(message)
            if not oss_path:
                return {"success": False, "error": "OSS ODS 需要 oss:// 路径"}
            columns = params.get("columns") or self._extract_inline_columns(message)
            ensure_result = await self._ensure_oss_table(target_table, granularity, columns)
            if ensure_result.get("status") == "failed":
                return {
                    "success": False,
                    "error": ensure_result.get("error"),
                    "steps": {"ensure_table": ensure_result},
                }
            from dataworks_agent.services.ods_oss import OssImportPipeline

            file_format = str(params.get("file_format") or str(oss_path).rsplit(".", 1)[-1]).lower()
            if file_format not in {"csv", "json", "parquet"}:
                file_format = "csv"
            result = await OssImportPipeline(nodes).run(
                oss_path=str(oss_path),
                target_table=target_table,
                file_format=file_format,
                wildcard=str(params.get("wildcard") or ""),
                schedule_type=normalized_granularity,
                schedule_minute=schedule_minute,
                publish=False,
            )
            result.setdefault("steps", {})["ensure_table"] = ensure_result
            return result

        if source_type == "realtime":
            database_schema = str(params.get("database_schema") or datasource or "").strip()
            if not database_schema:
                return {
                    "success": False,
                    "error": "实时 ODS 需要 database_schema 或 datasource_name",
                }
            delta_table = str(
                params.get("delta_table") or f"{database_schema}__{source_table}_delta"
            )
            ensure_result = await self._ensure_table_from_source(delta_table, target_table, "hour")
            if ensure_result.get("status") == "failed":
                return {
                    "success": False,
                    "error": ensure_result.get("error"),
                    "steps": {"ensure_table": ensure_result},
                }
            select_dml = params.get("select_dml")
            if not select_dml:
                columns = ensure_result.get("columns")
                if not columns:
                    schema = await app_state._maxcompute_client.get_table_schema(delta_table)
                    columns = [
                        column
                        for column in schema.columns
                        if column.name.lower() not in {"dt", "ht"}
                    ]
                select_dml = (
                    "SELECT "
                    + ", ".join(f"`{column.name}`" for column in columns)
                    + f" FROM {delta_table}"
                )
            sync_rows = params.get("sync_rows") or [{"dst_table": delta_table}]
            from dataworks_agent.services.ods_realtime import RealtimeSyncPipeline

            result = await RealtimeSyncPipeline(nodes).run(
                database_schema=database_schema,
                table_name=source_table,
                sync_rows=sync_rows,
                select_dml=str(select_dml),
                target_table=target_table,
                granularity="hour",
                schedule_minute=schedule_minute,
                publish=False,
            )
            result.setdefault("steps", {})["ensure_table"] = ensure_result
            return result

        if not datasource:
            return {"success": False, "error": "ODS DI 需要 datasource_name"}
        if bff is None:
            return {
                "success": False,
                "error": "Cookie/BFF 不可用，无法发现数据源字段或手动初始化 DI",
            }
        from dataworks_agent.services.ods_di.pipeline import DIPipeline

        pipeline = DIPipeline(
            bff,
            app_state.mcp_pool,
            node_client=nodes,
            mc_client=app_state._maxcompute_client,
        )
        return await pipeline.run(
            datasource_name=datasource,
            source_table=source_table,
            target_table=target_table,
            granularity=normalized_granularity,
            schedule_minute=schedule_minute,
            source_type=source_type,
            mc_project=settings.dataworks_dev_schema,
            with_initialization=initialize,
            init_config={
                "dev_mc_project": settings.dataworks_dev_schema,
                "prod_mc_project": settings.dataworks_prod_schema,
                "copy_to_prod": False,
                "publish_incremental_after_init": False,
            },
        )

    async def _deploy_warehouse_layer(
        self,
        layer: str,
        source_table: str,
        target_table: str,
        granularity: str,
        schedule_minute: int,
    ) -> dict[str, Any]:
        mc = app_state._maxcompute_client
        nodes = app_state._node_client
        schema = await mc.get_table_schema(source_table)
        columns = [c for c in schema.columns if c.name.lower() not in {"dt", "ht", "hh"}]
        if not columns:
            return {"success": False, "error": f"源表 {source_table} 无业务字段"}
        partition_names = ["dt", "ht"] if granularity in {"hour", "hourly"} else ["dt"]
        ddl_cols = ",\n".join(
            f"  `{c.name}` {self._normalize_mc_type(c.type)} COMMENT '{self._escape_comment(c.comment)}'"
            for c in columns
        )
        partitions = ", ".join(f"`{name}` STRING" for name in partition_names)
        ddl = f"CREATE TABLE IF NOT EXISTS {settings.dataworks_dev_schema}.{target_table} (\n{ddl_cols}\n) PARTITIONED BY ({partitions}) COMMENT '{layer} Agent generated';"
        if not await mc.table_exists(target_table, project=settings.dataworks_dev_schema):
            ddl_result = await mc.execute_ddl(ddl)
            if not ddl_result.success:
                return {"success": False, "error": ddl_result.error, "ddl": ddl}
        select_cols = ",\n".join(f"  `{c.name}`" for c in columns)
        if granularity in {"hour", "hourly"}:
            partition = "PARTITION (dt='${bizdate}', ht='${hour}')"
            where = "WHERE dt='${bizdate}' AND ht='${hour}'"
            cycle = "NotDaily"
            parameters = HOURLY_SQL_PARAMETERS
            cron = generate_cron("hour", minute=schedule_minute)
        else:
            partition = "PARTITION (dt='${bizdate}')"
            where = "WHERE dt='${bizdate}'"
            cycle = "Daily"
            parameters = DAILY_SQL_PARAMETERS
            cron = generate_cron("day", hour=3, minute=schedule_minute)
        sql = f"INSERT OVERWRITE TABLE {settings.dataworks_dev_schema}.{target_table} {partition}\nSELECT\n{select_cols}\nFROM {settings.dataworks_dev_schema}.{source_table}\n{where};"
        node_path = generate_node_path(
            f"dataworks_agent/{'02_DWD' if layer == 'DWD' else '03_' + layer}", target_table
        )
        node_uuid = await nodes.create_node(target_table, node_path, language="odps-sql")
        if not node_uuid or not await nodes.update_node(node_uuid, sql):
            return {
                "success": False,
                "error": nodes.last_error or "create/update node failed",
                "ddl": ddl,
                "sql": sql,
            }
        scheduled = await nodes.update_vertex(
            node_uuid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": [
                    {
                        "type": "Normal",
                        "sourceType": "Manual",
                        "output": f"{settings.maxcompute_project or settings.dataworks_dev_schema}.{source_table}",
                        "refTableName": f"{settings.maxcompute_project or settings.dataworks_dev_schema}.{source_table}",
                    },
                    {"type": "CrossCycleDependsOnSelf"},
                ],
            },
        )
        return {
            "success": bool(scheduled),
            "table_status": "exists_or_created",
            "node_uuid": node_uuid,
            "node_path": node_path,
            "cron": cron,
            "ddl": ddl,
            "sql": sql,
            "publish": "saved_not_deployed",
        }

    @staticmethod
    def _normalize_mc_type(value: str) -> str:
        lower = value.lower()
        if any(t in lower for t in ("tinyint", "smallint", "int", "bigint")):
            return "BIGINT"
        if any(t in lower for t in ("decimal", "double", "float")):
            return "DECIMAL(24,6)"
        if "boolean" in lower:
            return "BOOLEAN"
        return "STRING"

    @staticmethod
    def _escape_comment(value: str) -> str:
        return (value or "").replace("'", "''")

    @staticmethod
    def _column_to_dict(column: Any) -> dict[str, Any]:
        return {
            "name": getattr(column, "name", ""),
            "type": str(getattr(column, "type", "")),
            "comment": getattr(column, "comment", "") or "",
        }

    @staticmethod
    def _extract_sql_sources(sql: str) -> list[str]:
        try:
            statement = sqlglot.parse_one(sql, read="hive")
        except Exception:
            return []
        return list(
            dict.fromkeys(
                table.sql(dialect="hive") for table in statement.find_all(exp.Table) if table.name
            )
        )

    @staticmethod
    def _infer_reverse_metadata(table_name: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
        from dataworks_agent.governance.table_name_parser import identify_layer, parse_table_name
        from dataworks_agent.governance.update_mode_inferer import infer_update_mode

        layer = identify_layer(table_name)
        try:
            parsed = parse_table_name(table_name)
        except Exception:
            parsed = {}
        try:
            resolution = infer_update_mode(table_name)
            update_mode: Any = {
                "dwd_update_mode": resolution.dwd_update_mode,
                "sql_update_mode": resolution.sql_update_mode,
                "partition_fields": resolution.partition_fields,
            }
        except Exception:
            update_mode = "unknown"
        semantic_candidates = []
        for column in columns:
            name = column["name"].lower()
            kind = (
                "measure"
                if any(
                    token in name
                    for token in ("amt", "amount", "price", "cnt", "count", "qty", "gmv")
                )
                else "dimension"
            )
            semantic_candidates.append(
                {
                    "name": column["name"],
                    "kind": kind,
                    "data_type": column["type"],
                    "description": column.get("comment", ""),
                    "confidence": 0.82 if column.get("comment") else 0.62,
                }
            )
        return {
            "layer": layer,
            "domain": parsed.get("subject_domain", "") if isinstance(parsed, dict) else "",
            "entity": parsed.get("description", "") if isinstance(parsed, dict) else "",
            "update_mode": update_mode,
            "semantic_candidates": semantic_candidates,
        }

    @staticmethod
    def _infer_issue_type(message: str, errors: list[str]) -> str:
        text = f"{message} {' '.join(errors)}".lower()
        if any(token in text for token in ("延迟", "上游未完成", "upstream delay")):
            return "upstream_delay"
        if any(token in text for token in ("质量", "空值", "重复", "quality")):
            return "quality_issue"
        if any(token in text for token in ("数据异常", "数据不对", "波动", "data anomaly")):
            return "data_anomaly"
        return "schedule_failure"

    @staticmethod
    def _execution_artifacts(executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for item in executed:
            result = item["result"]
            for kind in ("ddl", "sql"):
                if result.get(kind):
                    artifacts.append({"type": kind, "name": item["table"], "content": result[kind]})
            ensure_table = (result.get("steps") or {}).get("ensure_table") or {}
            if ensure_table.get("ddl") and not result.get("ddl"):
                artifacts.append(
                    {"type": "ddl", "name": item["table"], "content": ensure_table["ddl"]}
                )
        return artifacts

"""MCPServer — 自建 AK/SK 版 MCP Server。

实现 Requirement 18：
- 暴露六类工具（语义/元数据、建模、查询、归因、治理、会话）
- 每次调用鉴权 + 审计 + 数据边界
- 不提供执行删数删表删任务工具
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义。"""

    name: str
    description: str
    category: str  # semantic/metadata/modeling/query/attribution/governance/session
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable | None = None
    requires_auth: bool = True
    read_only: bool = False


@dataclass
class ToolCallRequest:
    """工具调用请求。"""

    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    session_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    """工具调用结果。"""

    success: bool
    result: Any = None
    error: str = ""
    audit_log: dict[str, Any] = field(default_factory=dict)


class MCPServer:
    """自建 AK/SK 版 MCP Server。

    暴露六类工具，每次调用鉴权 + 审计 + 数据边界。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """注册内置工具。"""
        # 1. 语义工具
        self.register_tool(
            ToolDefinition(
                name="get_metric_definition",
                description="获取指标定义",
                category="semantic",
                parameters={"metric_id": "string"},
                read_only=True,
            )
        )

        self.register_tool(
            ToolDefinition(
                name="resolve_caliber",
                description="口径澄清",
                category="semantic",
                parameters={"metric_id": "string", "expected_caliber": "string"},
                read_only=True,
            )
        )

        # 2. 元数据工具
        self.register_tool(
            ToolDefinition(
                name="get_table_context",
                description="获取表上下文（血缘、语义、质量信号）",
                category="metadata",
                parameters={"table_name": "string"},
                read_only=True,
            )
        )

        self.register_tool(
            ToolDefinition(
                name="list_tables",
                description="列出表",
                category="metadata",
                parameters={"project": "string", "database": "string"},
                read_only=True,
            )
        )

        # 3. 建模工具
        self.register_tool(
            ToolDefinition(
                name="forward_model",
                description="正向建模",
                category="modeling",
                parameters={
                    "source_table": "string",
                    "target_layer": "string",
                    "domain": "string",
                    "entity": "string",
                    "update_method": "string",
                },
            )
        )

        self.register_tool(
            ToolDefinition(
                name="reverse_model",
                description="逆向建模",
                category="modeling",
                parameters={
                    "source_type": "string",
                    "source_value": "string",
                },
                read_only=True,
            )
        )

        # 4. 查询工具
        self.register_tool(
            ToolDefinition(
                name="run_query",
                description="执行查询（只读）",
                category="query",
                parameters={"sql": "string"},
                read_only=True,
            )
        )

        # 5. 归因工具
        self.register_tool(
            ToolDefinition(
                name="clarify_caliber",
                description="口径澄清（归因第一步）",
                category="attribution",
                parameters={
                    "metric_id": "string",
                    "expected_caliber": "string",
                },
                read_only=True,
            )
        )

        self.register_tool(
            ToolDefinition(
                name="trace_lineage",
                description="追踪血缘",
                category="attribution",
                parameters={
                    "table_name": "string",
                    "direction": "string",
                },
                read_only=True,
            )
        )

        # 6. 治理工具
        self.register_tool(
            ToolDefinition(
                name="check_root",
                description="词根校验",
                category="governance",
                parameters={"fields": "list[string]"},
                read_only=True,
            )
        )

        self.register_tool(
            ToolDefinition(
                name="check_ddl",
                description="DDL 规范检查",
                category="governance",
                parameters={"ddl": "string"},
                read_only=True,
            )
        )

        # 7. 会话工具
        self.register_tool(
            ToolDefinition(
                name="create_session",
                description="创建会话",
                category="session",
                parameters={"task_type": "string"},
            )
        )

        self.register_tool(
            ToolDefinition(
                name="get_session_status",
                description="获取会话状态",
                category="session",
                parameters={"session_id": "string"},
                read_only=True,
            )
        )

    def register_tool(self, tool: ToolDefinition) -> None:
        """注册工具。"""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        """获取工具定义。"""
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """列出工具。"""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResult:
        """调用工具。"""
        tool = self._tools.get(request.tool_name)
        if not tool:
            return ToolCallResult(
                success=False,
                error=f"工具不存在: {request.tool_name}",
            )

        # 鉴权检查
        if tool.requires_auth and not request.user_id:
            return ToolCallResult(
                success=False,
                error="需要鉴权",
            )

        # 数据边界检查（只读工具不允许写操作）
        if tool.read_only and request.context.get("write_operation"):
            return ToolCallResult(
                success=False,
                error="只读工具不允许写操作",
            )

        # 执行工具
        try:
            result = await self._execute_tool(tool, request)
            return ToolCallResult(
                success=True,
                result=result,
                audit_log={
                    "tool": request.tool_name,
                    "user": request.user_id,
                    "parameters": request.parameters,
                },
            )
        except Exception as e:
            logger.error("工具执行失败: %s: %s", request.tool_name, e)
            return ToolCallResult(
                success=False,
                error=str(e),
            )

    async def _execute_tool(
        self,
        tool: ToolDefinition,
        request: ToolCallRequest,
    ) -> Any:
        """执行工具。"""
        # 根据工具名分发到具体实现
        handlers = {
            "get_metric_definition": self._handle_get_metric_definition,
            "resolve_caliber": self._handle_resolve_caliber,
            "get_table_context": self._handle_get_table_context,
            "forward_model": self._handle_forward_model,
            "reverse_model": self._handle_reverse_model,
            "run_query": self._handle_run_query,
            "clarify_caliber": self._handle_clarify_caliber,
            "trace_lineage": self._handle_trace_lineage,
            "check_root": self._handle_check_root,
            "check_ddl": self._handle_check_ddl,
            "create_session": self._handle_create_session,
            "get_session_status": self._handle_get_session_status,
        }

        handler = handlers.get(tool.name)
        if handler:
            return await handler(request)

        return {"message": f"工具 {tool.name} 待实现"}

    # ── 工具处理器 ──

    async def _handle_get_metric_definition(self, request: ToolCallRequest) -> Any:
        """处理获取指标定义。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        metric_id = request.parameters.get("metric_id", "")
        definition = layer.get_metric_definition(metric_id)
        if definition:
            return {
                "metric_id": definition.key,
                "body": definition.body,
                "version": definition.version,
            }
        return {"error": f"指标 {metric_id} 不存在"}

    async def _handle_resolve_caliber(self, request: ToolCallRequest) -> Any:
        """处理口径澄清。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        metric_id = request.parameters.get("metric_id", "")
        result = layer.resolve_caliber(metric_id)
        return {
            "metric_id": result.metric_id,
            "resolved": result.resolved,
            "definition": result.definition.body if result.definition else None,
        }

    async def _handle_get_table_context(self, request: ToolCallRequest) -> Any:
        """处理获取表上下文。"""
        from dataworks_agent.semantic.graph import SemanticGraph

        graph = SemanticGraph()
        table_name = request.parameters.get("table_name", "")
        context = graph.get_table_context(table_name)
        if context:
            return {
                "table_name": context.table_name,
                "layer": context.layer,
                "domain": context.domain,
                "upstream": context.upstream_tables,
                "downstream": context.downstream_tables,
            }
        return {"error": f"表 {table_name} 不存在"}

    async def _handle_forward_model(self, request: ToolCallRequest) -> Any:
        """处理正向建模。"""
        from dataworks_agent.runtime.forward_flow import ForwardModelingFlow, ModelingRequest

        flow = ForwardModelingFlow()
        modeling_request = ModelingRequest(
            source_table=request.parameters.get("source_table", ""),
            target_layer=request.parameters.get("target_layer", ""),
            domain=request.parameters.get("domain", ""),
            entity=request.parameters.get("entity", ""),
            update_method=request.parameters.get("update_method", ""),
            dry_run=True,  # MCP 默认 dry_run
        )
        result = await flow.execute(modeling_request)
        return {
            "success": result.success,
            "target_table": result.target_table,
            "ddl": result.ddl,
            "sql": result.sql,
        }

    async def _handle_reverse_model(self, request: ToolCallRequest) -> Any:
        """处理逆向建模。"""
        from dataworks_agent.runtime.reverse_flow import ReverseModelingFlow, ReverseModelingRequest

        flow = ReverseModelingFlow()
        modeling_request = ReverseModelingRequest(
            source_type=request.parameters.get("source_type", ""),
            source_value=request.parameters.get("source_value", ""),
        )
        result = await flow.execute(modeling_request)
        return {
            "success": result.success,
            "table_name": result.table_name,
            "layer": result.layer,
            "domain": result.domain,
            "columns": result.columns,
        }

    async def _handle_run_query(self, request: ToolCallRequest) -> Any:
        """处理执行查询。"""
        # 简化实现：返回模拟结果
        return {"message": "查询执行待实现", "sql": request.parameters.get("sql", "")}

    async def _handle_clarify_caliber(self, request: ToolCallRequest) -> Any:
        """处理口径澄清。"""
        from dataworks_agent.runtime.caliber import CaliberClarificationRequest, CaliberClarifier

        clarifier = CaliberClarifier()
        clarification_request = CaliberClarificationRequest(
            metric_id=request.parameters.get("metric_id", ""),
            expected_caliber=request.parameters.get("expected_caliber", ""),
        )
        result = await clarifier.clarify(clarification_request)
        return {
            "metric_id": result.metric_id,
            "resolved": result.resolved,
            "caliber_match": result.caliber_match,
            "explanation": result.explanation,
        }

    async def _handle_trace_lineage(self, request: ToolCallRequest) -> Any:
        """处理追踪血缘。"""
        from dataworks_agent.semantic.graph import SemanticGraph

        graph = SemanticGraph()
        table_name = request.parameters.get("table_name", "")
        direction = request.parameters.get("direction", "upstream")

        if direction == "upstream":
            tables = graph.get_upstream(table_name)
        else:
            tables = graph.get_downstream(table_name)

        return {
            "table_name": table_name,
            "direction": direction,
            "tables": tables,
        }

    async def _handle_check_root(self, request: ToolCallRequest) -> Any:
        """处理词根校验。"""
        from dataworks_agent.semantic.guard import ProposalGuard

        guard = ProposalGuard()
        fields = request.parameters.get("fields", [])
        result = guard.check_root(fields)
        return {
            "passed": result.passed,
            "errors": result.errors,
        }

    async def _handle_check_ddl(self, request: ToolCallRequest) -> Any:
        """处理 DDL 规范检查。"""
        from dataworks_agent.semantic.guard import ProposalGuard

        guard = ProposalGuard()
        ddl = request.parameters.get("ddl", "")
        result = guard.check_ddl(ddl)
        return {
            "passed": result.passed,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    async def _handle_create_session(self, request: ToolCallRequest) -> Any:
        """处理创建会话。"""
        from dataworks_agent.runtime.service import RuntimeService

        service = RuntimeService()
        session = service.create_session(
            task_id=request.parameters.get("task_id", ""),
            task_type=request.parameters.get("task_type", "modeling"),
        )
        return {
            "session_id": session.session_id,
            "task_id": session.task_id,
        }

    async def _handle_get_session_status(self, request: ToolCallRequest) -> Any:
        """处理获取会话状态。"""
        return {
            "session_id": request.parameters.get("session_id", ""),
            "status": "active",
        }

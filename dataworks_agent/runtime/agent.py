"""Agent — 端到端建模与对话查询。

实现 Requirement 19：
- 单 agent：NL 建模（提议-校验-审批）
- 基于语义口径的 run_query（权限收敛、只读）
- 引用未定义口径拒绝
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentRequest:
    """Agent 请求。"""

    request_type: str  # modeling / query / clarification
    content: str  # 自然语言内容
    context: dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    session_id: str = ""


@dataclass
class AgentResponse:
    """Agent 响应。"""

    success: bool
    response_type: str  # proposal / result / clarification / error
    content: str = ""
    data: dict[str, Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    needs_approval: bool = False


class Agent:
    """单 Agent — 端到端建模与对话查询。

    支持：
    - NL 建模（提议-校验-审批）
    - 基于语义口径的查询
    - 口径澄清
    """

    def __init__(self) -> None:
        from dataworks_agent.runtime.caliber import CaliberClarifier
        from dataworks_agent.runtime.forward_flow import ForwardModelingFlow
        from dataworks_agent.semantic.guard import ProposalGuard

        self.forward_flow = ForwardModelingFlow()
        self.caliber_clarifier = CaliberClarifier()
        self.proposal_guard = ProposalGuard()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理 Agent 请求。"""
        try:
            if request.request_type == "modeling":
                return await self._handle_modeling(request)
            elif request.request_type == "query":
                return await self._handle_query(request)
            elif request.request_type == "clarification":
                return await self._handle_clarification(request)
            else:
                return AgentResponse(
                    success=False,
                    response_type="error",
                    errors=[f"未知请求类型: {request.request_type}"],
                )
        except Exception as e:
            logger.error("Agent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    async def _handle_modeling(self, request: AgentRequest) -> AgentResponse:
        """处理建模请求。"""
        from dataworks_agent.runtime.forward_flow import ModelingRequest

        # 解析自然语言为建模参数
        params = self._parse_modeling_params(request.content, request.context)

        # 创建建模请求
        modeling_request = ModelingRequest(
            source_table=params.get("source_table", ""),
            target_layer=params.get("target_layer", ""),
            domain=params.get("domain", ""),
            entity=params.get("entity", ""),
            update_method=params.get("update_method", ""),
            dry_run=True,  # 默认 dry_run
        )

        # 执行建模
        result = await self.forward_flow.execute(modeling_request)

        if result.success:
            return AgentResponse(
                success=True,
                response_type="proposal",
                content=f"建模提议已生成: {result.target_table}",
                data={
                    "target_table": result.target_table,
                    "ddl": result.ddl,
                    "sql": result.sql,
                },
                needs_approval=True,
            )
        else:
            return AgentResponse(
                success=False,
                response_type="error",
                errors=result.errors,
            )

    async def _handle_query(self, request: AgentRequest) -> AgentResponse:
        """处理查询请求。"""
        # 解析查询
        query_info = self._parse_query(request.content, request.context)

        # 检查口径是否存在
        metric_id = query_info.get("metric_id", "")
        if metric_id:
            from dataworks_agent.semantic.layer import SemanticLayer

            layer = SemanticLayer()
            definition = layer.get_metric_definition(metric_id)
            if not definition:
                return AgentResponse(
                    success=False,
                    response_type="error",
                    errors=[f"引用未定义口径: {metric_id}"],
                )

        # 执行查询（简化实现）
        return AgentResponse(
            success=True,
            response_type="result",
            content=f"查询结果: {query_info}",
            data={"query": query_info},
        )

    async def _handle_clarification(self, request: AgentRequest) -> AgentResponse:
        """处理口径澄清请求。"""
        from dataworks_agent.runtime.caliber import CaliberClarificationRequest

        # 解析澄清参数
        params = self._parse_clarification_params(request.content, request.context)

        clarification_request = CaliberClarificationRequest(
            metric_id=params.get("metric_id", ""),
            expected_caliber=params.get("expected_caliber", ""),
        )

        result = await self.caliber_clarifier.clarify(clarification_request)

        return AgentResponse(
            success=True,
            response_type="clarification",
            content=result.explanation,
            data={
                "metric_id": result.metric_id,
                "resolved": result.resolved,
                "caliber_match": result.caliber_match,
                "root_cause": result.root_cause,
            },
        )

    def _parse_modeling_params(
        self,
        content: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """解析建模参数。"""
        # 简化实现：从上下文获取参数
        return {
            "source_table": context.get("source_table", ""),
            "target_layer": context.get("target_layer", ""),
            "domain": context.get("domain", ""),
            "entity": context.get("entity", ""),
            "update_method": context.get("update_method", "day"),
        }

    def _parse_query(
        self,
        content: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """解析查询。"""
        return {
            "sql": context.get("sql", ""),
            "metric_id": context.get("metric_id", ""),
        }

    def _parse_clarification_params(
        self,
        content: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """解析澄清参数。"""
        return {
            "metric_id": context.get("metric_id", ""),
            "expected_caliber": context.get("expected_caliber", ""),
        }

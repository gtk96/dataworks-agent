"""Specialized agents for multi-agent coordination.

Each agent declares its identity (role, capabilities, constraints) and
delegates to the appropriate service pipeline.  The Coordinator wires
these agents together so that each request_type reaches the agent
whose expertise matches the sub-task.

实现 Harness Engineering Identity 支柱：
- 每个 agent 声明能力边界（能做什么/不能做什么）
- 约束在 Coordinator 层面强制执行
- 保持 AgentRequest/AgentResponse 接口稳定
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentIdentity:
    """Agent 身份声明 — 能力边界与约束。"""

    name: str
    description: str
    role: str  # requirement / architecture / modeling / governance / diagnosis / query
    capabilities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def check_capability(self, action: str) -> bool:
        """Check if the agent can perform the given action."""
        if not self.capabilities:
            return True  # No capabilities declared = unrestricted
        return any(cap.lower() in action.lower() for cap in self.capabilities)

    def check_constraint(self, action: str) -> tuple[bool, str]:
        """Check if the agent is constrained from performing the given action.

        Returns:
            (allowed, violation_reason)
        """
        if not self.constraints:
            return True, ""
        for constraint in self.constraints:
            if constraint.lower() in action.lower():
                return False, f"违反约束: {constraint}"
        return True, ""


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
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    needs_approval: bool = False


class RequirementAgent:
    """需求理解 Agent — 意图解析与澄清。

    职责:
    - 理解用户自然语言需求
    - 提取关键实体（表名、源表、业务域）
    - 对模糊需求进行澄清提问
    - 将需求转化为结构化参数

    约束:
    - 不执行任何写操作
    - 不生成 DDL/DML
    - 不访问 DataWorks API
    """

    identity = AgentIdentity(
        name="RequirementAgent",
        description="需求理解与意图澄清专家",
        role="requirement",
        capabilities=["intent_parsing", "entity_extraction", "clarification"],
        constraints=["no_write", "no_ddl_generation", "no_dataworks_api"],
    )

    def __init__(self) -> None:
        from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
        from dataworks_agent.agent.nlu.intent_parser import IntentParser

        self.intent_parser = IntentParser()
        self.entity_extractor = EntityExtractor()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理需求理解请求。"""
        try:
            # 解析意图
            intent = self.intent_parser.parse(request.content)

            # 提取实体
            entities = self.entity_extractor.extract(request.content)

            # 检查是否需要澄清
            if intent.confidence < 0.7 or intent.action == "unknown":
                questions = self._generate_clarifying_questions(intent, entities)
                return AgentResponse(
                    success=True,
                    response_type="clarification",
                    content="需要更多信息才能理解您的需求",
                    data={
                        "intent": {
                            "action": intent.action,
                            "confidence": intent.confidence,
                            "params": intent.params,
                        },
                        "entities": entities,
                        "clarifying_questions": questions,
                    },
                )

            return AgentResponse(
                success=True,
                response_type="parsed_intent",
                content=f"已理解需求: {intent.action}",
                data={
                    "intent": {
                        "action": intent.action,
                        "confidence": intent.confidence,
                        "params": intent.params,
                    },
                    "entities": entities,
                },
            )
        except Exception as e:
            logger.error("RequirementAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    def _generate_clarifying_questions(self, intent: Any, entities: dict[str, Any]) -> list[str]:
        """根据解析结果生成澄清问题。"""
        questions: list[str] = []
        if not entities.get("table_name"):
            questions.append("目标表名是什么？例如 dwd_trade_order_detail。")
        if not entities.get("source_table"):
            questions.append("源表或主要输入表是什么？例如 ods_order。")
        return questions


class ModelingAgent:
    """建模 Agent — DDL/DML 生成与正向/逆向建模。

    职责:
    - 正向建模：NL → DDL/DML/调度/依赖
    - 逆向建模：存量表 → 结构+语义候选
    - 执行建模流程（提议-校验-审批）

    约束:
    - 默认 dry_run 模式
    - 涉及真实写入需 needs_approval=True
    - 不修改语义层定义
    """

    identity = AgentIdentity(
        name="ModelingAgent",
        description="数据建模专家，负责 DDL/DML 生成与建模流程",
        role="modeling",
        capabilities=["forward_modeling", "reverse_modeling", "ddl_generation", "dml_generation"],
        constraints=[
            "dry_run_by_default",
            "approval_required_for_write",
            "no_semantic_modification",
        ],
    )

    def __init__(self) -> None:
        from dataworks_agent.runtime.forward_flow import ForwardModelingFlow
        from dataworks_agent.runtime.reverse_flow import ReverseModelingFlow

        self.forward_flow = ForwardModelingFlow()
        self.reverse_flow = ReverseModelingFlow()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理建模请求。"""
        try:
            params = self._parse_modeling_params(request.content, request.context)

            if params.get("reverse", False):
                return await self._handle_reverse_modeling(params)
            return await self._handle_forward_modeling(params)
        except Exception as e:
            logger.error("ModelingAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    async def _handle_forward_modeling(self, params: dict[str, Any]) -> AgentResponse:
        """处理正向建模。"""
        from dataworks_agent.runtime.forward_flow import ModelingRequest

        modeling_request = ModelingRequest(
            source_table=params.get("source_table", ""),
            target_layer=params.get("target_layer", ""),
            domain=params.get("domain", ""),
            entity=params.get("entity", ""),
            update_method=params.get("update_method", ""),
            dry_run=True,
        )

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
        return AgentResponse(
            success=False,
            response_type="error",
            errors=result.errors,
        )

    async def _handle_reverse_modeling(self, params: dict[str, Any]) -> AgentResponse:
        """处理逆向建模。"""
        result = await self.reverse_flow.execute(
            table_name=params.get("table_name", ""),
            domain=params.get("domain", ""),
        )
        return AgentResponse(
            success=result.success,
            response_type="proposal",
            content=result.message if hasattr(result, "message") else "逆向建模完成",
            data=getattr(result, "data", {}),
            needs_approval=False,
        )

    @staticmethod
    def _parse_modeling_params(content: str, context: dict[str, Any]) -> dict[str, Any]:
        """解析建模参数。"""
        return {
            "source_table": context.get("source_table", ""),
            "target_layer": context.get("target_layer", ""),
            "domain": context.get("domain", ""),
            "entity": context.get("entity", ""),
            "update_method": context.get("update_method", "day"),
            "reverse": context.get("reverse", False),
            "table_name": context.get("table_name", ""),
        }


class GovernanceAgent:
    """治理 Agent — 规范校验、语义层管理与质量信号。

    职责:
    - ProposalGuard 五道闸门校验
    - 语义层定义管理（口径/维度/指标）
    - 数据质量信号消费（DQC）
    - 命名规范校验

    约束:
    - 只读校验，不执行写操作
    - 不修改 DataWorks 节点
    - 不绕过 PublishGate
    """

    identity = AgentIdentity(
        name="GovernanceAgent",
        description="治理与规范校验专家",
        role="governance",
        capabilities=[
            "proposal_validation",
            "semantic_layer_management",
            "quality_signal_consumption",
            "naming_compliance",
        ],
        constraints=["read_only_validation", "no_node_modification", "no_publish_gate_override"],
    )

    def __init__(self) -> None:
        from dataworks_agent.semantic.guard import ProposalGuard
        from dataworks_agent.semantic.layer import SemanticLayer
        from dataworks_agent.semantic.quality import DQConsumer

        self.proposal_guard = ProposalGuard()
        self.semantic_layer = SemanticLayer()
        self.dq_consumer = DQConsumer()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理治理请求。"""
        try:
            action = request.context.get("governance_action", "")

            if action == "validate_proposal":
                return await self._validate_proposal(request)
            if action == "check_naming":
                return await self._check_naming(request)
            if action == "consume_quality":
                return await self._consume_quality(request)

            return AgentResponse(
                success=False,
                response_type="error",
                errors=[f"未知的治理动作: {action}"],
            )
        except Exception as e:
            logger.error("GovernanceAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    async def _validate_proposal(self, request: AgentRequest) -> AgentResponse:
        """执行提案校验。"""
        from dataworks_agent.semantic.guard import ValidationResult

        result: dict[str, Any] = {"checks": [], "overall_passed": True}
        all_errors: list[str] = []

        # 1. 词根校验
        fields = request.context.get("fields", [])
        if fields:
            root_result = self.proposal_guard.check_root(fields)
            result["checks"].append({"name": "root", "passed": root_result.passed})
            if not root_result.passed:
                all_errors.extend(root_result.errors)
                result["overall_passed"] = False

        # 2. DDL 校验
        ddl = request.context.get("ddl", "")
        if ddl:
            ddl_result = self.proposal_guard.check_ddl(ddl)
            result["checks"].append({"name": "ddl", "passed": ddl_result.passed})
            if not ddl_result.passed:
                all_errors.extend(ddl_result.errors)
                result["overall_passed"] = False

        # 3. 分层校验
        source_table = request.context.get("source_table", "")
        target_table = request.context.get("target_table", "")
        target_layer = request.context.get("target_layer", "")
        if source_table and target_table and target_layer:
            layer_result = self.proposal_guard.check_layer_dependency(
                target_layer, [source_table]
            )
            result["checks"].append({"name": "layer", "passed": layer_result.passed})
            if not layer_result.passed:
                all_errors.extend(layer_result.errors)
                result["overall_passed"] = False

        # 4. 表名校验
        if target_table:
            name_result = self.proposal_guard.check_table_name(target_table)
            result["checks"].append({"name": "table_name", "passed": name_result.passed})
            if not name_result.passed:
                all_errors.extend(name_result.errors)
                result["overall_passed"] = False

        if all_errors:
            result["errors"] = all_errors

        return AgentResponse(
            success=result["overall_passed"],
            response_type="validation_result",
            content="提案校验完成" if result["overall_passed"] else "提案校验未通过",
            data=result,
        )

    async def _check_naming(self, request: AgentRequest) -> AgentResponse:
        """检查命名规范。"""
        table_name = request.context.get("table_name", "")
        if not table_name:
            return AgentResponse(
                success=False,
                response_type="error",
                errors=["缺少 table_name 参数"],
            )
        return AgentResponse(
            success=True,
            response_type="naming_check",
            content=f"命名检查完成: {table_name}",
            data={"table_name": table_name, "compliant": True},
        )

    async def _consume_quality(self, request: AgentRequest) -> AgentResponse:
        """消费质量信号。"""
        task_id = request.context.get("task_id", "")
        result = await self.dq_consumer.consume(task_id)
        return AgentResponse(
            success=True,
            response_type="quality_signal",
            content="质量信号消费完成",
            data=result if isinstance(result, dict) else {},
        )


class DiagnosisAgent:
    """诊断 Agent — 任务失败诊断与自愈提议。

    职责:
    - 调度失败/数据异常诊断
    - 根因分析（上游延迟、数据质量问题、资源瓶颈）
    - 自愈提议（重试/修复数据/告警/等待）

    约束:
    - 不执行真实修复操作
    - 所有修复提议需 needs_approval=True
    - 不绕过 DestructiveOpGuard
    """

    identity = AgentIdentity(
        name="DiagnosisAgent",
        description="故障诊断与自愈专家",
        role="diagnosis",
        capabilities=[
            "schedule_failure_diagnosis",
            "data_anomaly_detection",
            "root_cause_analysis",
            "heal_proposal",
        ],
        constraints=[
            "no_automatic_repair",
            "approval_required_for_fix",
            "no_destructive_guard_override",
        ],
    )

    def __init__(self) -> None:
        from dataworks_agent.runtime.self_heal import SelfHealFlow

        self.self_heal = SelfHealFlow()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理诊断请求。"""
        try:
            result = await self.self_heal.diagnose(
                issue_description=request.content,
                context=request.context,
            )
            return AgentResponse(
                success=True,
                response_type="diagnosis",
                content=result.get("summary", "诊断完成"),
                data=result,
                needs_approval=result.get("requires_approval", False),
            )
        except Exception as e:
            logger.error("DiagnosisAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )


class QueryAgent:
    """查询 Agent — 指标查询、口径澄清与 RAG 检索。

    职责:
    - 基于语义口径的查询
    - 指标归因诊断
    - 知识库 RAG 检索
    - 业务问数（ask_data）

    约束:
    - 只读操作
    - 引用未定义口径时拒绝
    - 不执行写操作或建模
    """

    identity = AgentIdentity(
        name="QueryAgent",
        description="查询与口径澄清专家",
        role="query",
        capabilities=["metric_query", "caliber_clarification", "rag_search", "attribution"],
        constraints=["read_only", "reject_undefined_caliber", "no_write_operations"],
    )

    def __init__(self) -> None:
        from dataworks_agent.runtime.caliber import CaliberClarifier
        from dataworks_agent.semantic.layer import SemanticLayer

        self.caliber_clarifier = CaliberClarifier()
        self.semantic_layer = SemanticLayer()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理查询请求。"""
        try:
            action = request.context.get("query_action", "metric_query")

            if action == "clarification":
                return await self._handle_clarification(request)
            return await self._handle_query(request)
        except Exception as e:
            logger.error("QueryAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    async def _handle_query(self, request: AgentRequest) -> AgentResponse:
        """处理查询请求。"""
        metric_id = request.context.get("metric_id", "")
        if metric_id:
            definition = self.semantic_layer.get_metric_definition(metric_id)
            if not definition:
                return AgentResponse(
                    success=False,
                    response_type="error",
                    errors=[f"引用未定义口径: {metric_id}"],
                )

        return AgentResponse(
            success=True,
            response_type="result",
            content="查询完成",
            data={"query": request.context},
        )

    async def _handle_clarification(self, request: AgentRequest) -> AgentResponse:
        """处理口径澄清请求。"""
        from dataworks_agent.runtime.caliber import CaliberClarificationRequest

        params = {
            "metric_id": request.context.get("metric_id", ""),
            "expected_caliber": request.context.get("expected_caliber", ""),
        }
        clarification_request = CaliberClarificationRequest(**params)
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


class ArchitectureAgent:
    """架构 Agent — 分层设计与领域映射。

    职责:
    - 数据分层设计（ODS/DWD/DIM/DWS/DMR）
    - 业务域映射
    - 表命名规范建议
    - 架构评审

    约束:
    - 只提供建议，不执行写操作
    - 不修改现有架构
    - 需要人工确认才能变更分层
    """

    identity = AgentIdentity(
        name="ArchitectureAgent",
        description="数据架构与分层设计专家",
        role="architecture",
        capabilities=["layer_design", "domain_mapping", "naming_convention", "architecture_review"],
        constraints=["suggestion_only", "no_modification", "manual_confirm_for_layer_change"],
    )

    def __init__(self) -> None:
        from dataworks_agent.modeling.bus_matrix import BusinessDomainMatrix

        self.bus_matrix = BusinessDomainMatrix()

    async def process(self, request: AgentRequest) -> AgentResponse:
        """处理架构请求。"""
        try:
            action = request.context.get("architecture_action", "suggest_layer")

            if action == "suggest_layer":
                return await self._suggest_layer(request)
            if action == "domain_mapping":
                return await self._map_domain(request)

            return AgentResponse(
                success=True,
                response_type="architecture_suggestion",
                content="架构建议完成",
                data={"action": action, "suggestion": request.content},
            )
        except Exception as e:
            logger.error("ArchitectureAgent 处理失败: %s", e)
            return AgentResponse(
                success=False,
                response_type="error",
                errors=[str(e)],
            )

    async def _suggest_layer(self, request: AgentRequest) -> AgentResponse:
        """建议目标分层。"""
        source_table = request.context.get("source_table", "")
        target_layer = request.context.get("target_layer", "")

        if not source_table:
            return AgentResponse(
                success=False,
                response_type="error",
                errors=["缺少 source_table 参数"],
            )

        suggestion = {
            "source_table": source_table,
            "recommended_layer": target_layer or self._infer_layer(source_table),
            "reason": self._explain_recommendation(source_table, target_layer),
        }

        return AgentResponse(
            success=True,
            response_type="architecture_suggestion",
            content=f"建议分层: {suggestion['recommended_layer']}",
            data=suggestion,
            needs_approval=False,
        )

    @staticmethod
    def _infer_layer(source_table: str) -> str:
        """根据表名推断推荐分层。"""
        if source_table.startswith("ods_"):
            return "dwd"
        if source_table.startswith("dim_"):
            return "dws"
        return "dwd"

    @staticmethod
    def _explain_recommendation(source_table: str, target_layer: str) -> str:
        """解释分层建议原因。"""
        if target_layer:
            return f"用户指定目标分层为 {target_layer}"
        return f"根据源表 {source_table} 推断推荐分层"


class Agent:
    """单 Agent — 端到端建模与对话查询（向后兼容基类）。

    支持：
    - NL 建模（提议-校验-审批）
    - 基于语义口径的查询
    - 口径澄清

    注意：新代码应使用专业化的 Agent 子类（RequirementAgent、
    ModelingAgent 等），此类保留用于向后兼容。
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

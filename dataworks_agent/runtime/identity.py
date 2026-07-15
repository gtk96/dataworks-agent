"""Agent Identity — Harness Engineering 支柱一：角色定义与约束体系。

实现：
- AgentIdentity 声明每个专业 agent 的能力边界、行为约束、IO 契约
- AgentConstraint 提供运行时强制校验（超级红线、错误记录、操作规则三层金字塔）
- AgentRegistry 集中管理所有专业 agent 的身份声明
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ConstraintLevel(StrEnum):
    """约束层级（三层金字塔）。"""

    RED_LINE = "red_line"  # 超级红线：违反即严重事故，不可绕过
    ERROR_RECORD = "error_record"  # 错误记录：引起重视，反复出现则升级
    OPERATION_RULE = "operation_rule"  # 操作规则：建议性，可能被选择性忽略


@dataclass
class AgentConstraint:
    """单条行为约束。"""

    level: ConstraintLevel
    rule: str  # 规则描述
    reason: str  # 为什么这条规则重要
    violation_action: str = "reject"  # 违反时：reject / warn / log
    severity: str = "error"  # error / warning / info

    def enforce(self, condition: bool) -> bool:
        """检查约束是否满足。不满足则记录并决定是否阻断。"""
        if condition:
            return True

        if self.level == ConstraintLevel.RED_LINE:
            logger.error("[红线违反] %s: %s", self.rule, self.reason)
            return False

        if self.level == ConstraintLevel.ERROR_RECORD:
            logger.warning("[错误记录] %s: %s", self.rule, self.reason)
            return True  # 不阻断，但记录

        logger.info("[规则提示] %s: %s", self.rule, self.reason)
        return True


@dataclass
class AgentCapability:
    """单个能力声明。"""

    name: str
    description: str
    tool_ids: list[str] = field(default_factory=list)
    is_read_only: bool = False


@dataclass
class AgentIdentity:
    """Agent 身份声明 — Harness Identity 支柱。

    每个 Agent 必须有明确的：
    - 身份定义：这个角色定位是什么
    - IO 定义：输入输出的格式
    - 能力说明：可以使用哪些工具
    - 行为约束：标准流程、绝对禁止、约束层级
    """

    agent_type: str  # 与 AgentType 枚举对应
    name: str  # 人类可读名称
    description: str  # 角色定位
    capabilities: list[AgentCapability] = field(default_factory=list)
    constraints: list[AgentConstraint] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    mcp_tools: list[str] = field(default_factory=list)  # 可使用的 MCP 工具
    skill_paths: list[str] = field(default_factory=list)  # 可加载的 Skill 路径
    coordinator_roles: list[str] = field(default_factory=list)  # 协调者身上的显式角色

    def validate_input(self, data: dict[str, Any]) -> list[str]:
        """校验输入是否符合契约。返回违反列表（空表示通过）。"""
        violations: list[str] = []
        required_fields = self.input_schema.get("required", [])
        for field_name in required_fields:
            if field_name not in data:
                violations.append(f"缺少必填字段: {field_name}")
        return violations

    def validate_constraints(self, action: str, context: dict[str, Any]) -> list[str]:
        """执行约束检查。返回违反的红线列表。"""
        red_lines_violated: list[str] = []
        for constraint in self.constraints:
            if constraint.level != ConstraintLevel.RED_LINE:
                continue
            # 简单的关键词匹配检查
            if (
                constraint.rule in action or constraint.rule in str(context)
            ) and constraint.enforce(False):
                red_lines_violated.append(constraint.rule)
        return red_lines_violated

    def add_capability(self, name: str, description: str, **kwargs) -> None:
        """便捷添加能力。"""
        self.capabilities.append(AgentCapability(name=name, description=description, **kwargs))

    def add_constraint(self, level: ConstraintLevel, rule: str, reason: str, **kwargs) -> None:
        """便捷添加约束。"""
        self.constraints.append(AgentConstraint(level=level, rule=rule, reason=reason, **kwargs))


class AgentRegistry:
    """Agent 身份注册表。

    集中管理所有专业 agent 的身份声明，提供：
    - 按类型查询 agent 身份
    - 约束检查
    - 能力路由
    """

    def __init__(self) -> None:
        self._identities: dict[str, AgentIdentity] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        """注册内置的专业 agent 身份。"""
        # --- Requirement Agent ---
        req = AgentIdentity(
            agent_type="requirement",
            name="需求理解 Agent",
            description="理解用户业务目标，澄清模糊需求，确认执行意图",
            input_schema={
                "required": ["goal", "context"],
                "properties": {
                    "goal": "str - 用户原始业务目标",
                    "context": "dict - 会话上下文/历史参数",
                },
            },
            output_schema={
                "resolved_goal": "str - 澄清后的明确目标",
                "clarifications": "list[str] - 需要用户确认的问题",
                "intent_confirmed": "bool - 是否已确认",
            },
        )
        req.add_capability("intent_parsing", "解析用户自然语言为结构化意图")
        req.add_capability("clarification", "对模糊需求进行反问确认")
        req.add_capability("goal_resolution", "将业务目标映射到数据工程目标")
        req.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得跳过用户确认直接执行",
            "Human in the loop：阶段切换必须有用户确认",
        )
        req.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得编造知识库内容",
            "知识库未检索到知识必须如实回答",
        )
        self._identities["requirement"] = req

        # --- Architecture Agent ---
        arch = AgentIdentity(
            agent_type="architecture",
            name="架构设计 Agent",
            description="设计数据分层架构、表命名规范、业务域映射",
            input_schema={
                "required": ["domain", "entity", "source_type"],
                "properties": {
                    "domain": "str - 业务域",
                    "entity": "str - 实体名称",
                    "source_type": "str - 数据源类型",
                },
            },
            output_schema={
                "layer_strategy": "str - 分层策略（ODS/DWD/DWS/DIM）",
                "naming_convention": "str - 命名规范",
                "domain_mapping": "dict - 业务域映射",
            },
        )
        arch.add_capability("layer_design", "设计数据分层架构")
        arch.add_capability("naming_convention", "生成表命名规范")
        arch.add_capability("domain_mapping", "业务域与数据域映射")
        arch.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得违背分层规范",
            "ODS 不直接写 DWD 逻辑，DWD 不直接写 DWS 逻辑",
        )
        arch.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得跳过命名规范校验",
            "表名必须符合 word_root 和分层前缀规范",
        )
        self._identities["architecture"] = arch

        # --- Modeling Agent ---
        model = AgentIdentity(
            agent_type="modeling",
            name="建模 Agent",
            description="生成 DDL/DML、执行正向/逆向建模、创建节点",
            input_schema={
                "required": ["target_layer", "source_table", "target_table"],
                "properties": {
                    "target_layer": "str - 目标分层",
                    "source_table": "str - 源表",
                    "target_table": "str - 目标表",
                },
            },
            output_schema={
                "ddl": "str - 生成 DDL",
                "dml": "str - 生成 DML",
                "schedule_config": "dict - 调度配置",
                "dependency_plan": "dict - 依赖计划",
            },
        )
        model.add_capability("ddl_generation", "生成建表 DDL")
        model.add_capability("dml_generation", "生成数据加工 DML")
        model.add_capability("forward_modeling", "正向建模（NL → DDL/DML）")
        model.add_capability("reverse_modeling", "逆向建模（存量表 → 结构+语义）")
        model.add_capability("node_creation", "创建 DataWorks 节点")
        model.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得越界产出方案或 SQL 代码",
            "协调者禁止直接产出方案或 SQL 代码（必须调用子专家 Agent）",
        )
        model.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得跳过 Publish Gate 自动发布生产",
            "生产发布必须经人工审批闸口",
        )
        model.add_constraint(
            ConstraintLevel.ERROR_RECORD,
            "不得破坏性操作未走 guard",
            "DELETE/TRUNCATE/DROP 必须经过 DestructiveOpGuard",
        )
        self._identities["modeling"] = model

        # --- Governance Agent ---
        gov = AgentIdentity(
            agent_type="governance",
            name="治理 Agent",
            description="质量检查、命名规范验证、语义层管理、数据质量",
            input_schema={
                "required": ["artifact_type", "artifact_content"],
                "properties": {
                    "artifact_type": "str - 产物类型（ddl/sql/schedule）",
                    "artifact_content": "str - 产物内容",
                },
            },
            output_schema={
                "validation_passed": "bool - 是否通过",
                "violations": "list[str] - 违反项",
                "warnings": "list[str] - 警告项",
                "recommendations": "list[str] - 改进建议",
            },
        )
        gov.add_capability("naming_validation", "验证表名/字段名规范")
        gov.add_capability("ddl_compliance", "DDL 合规性检查")
        gov.add_capability("semantic_validation", "语义层一致性检查")
        gov.add_capability("quality_assessment", "数据质量评估")
        gov.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得自审自评",
            "生成者和裁判必须是两个角色",
        )
        gov.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得跳过强制检查项",
            "取消 AI '我觉得不需要检查' 的权力",
        )
        self._identities["governance"] = gov

        # --- Diagnosis Agent ---
        diag = AgentIdentity(
            agent_type="diagnosis",
            name="诊断 Agent",
            description="调度失败/数据异常诊断、修复提议、恢复方案",
            input_schema={
                "required": ["issue_type", "source"],
                "properties": {
                    "issue_type": "str - 问题类型",
                    "source": "str - 问题来源（节点ID/表名）",
                },
            },
            output_schema={
                "root_cause": "str - 根因分析",
                "heal_proposals": "list[dict] - 修复提议",
                "severity": "str - 严重程度",
                "requires_approval": "bool - 是否需要审批",
            },
        )
        diag.add_capability("failure_analysis", "调度失败根因分析")
        diag.add_capability("data_anomaly_detection", "数据异常检测")
        diag.add_capability("recovery_proposal", "生成恢复方案")
        diag.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得自动执行高风险修复",
            "高风险修复必须经人工确认",
        )
        diag.add_constraint(
            ConstraintLevel.ERROR_RECORD,
            "不得隐瞒失败原因",
            "诊断结果必须诚实，不得美化问题",
        )
        self._identities["diagnosis"] = diag

        # --- Query Agent ---
        query = AgentIdentity(
            agent_type="query",
            name="查询 Agent",
            description="指标查询、RAG 检索、数据问答、只读分析",
            input_schema={
                "required": ["question", "metric_id"],
                "properties": {
                    "question": "str - 自然语言问题",
                    "metric_id": "str - 可选的指标 ID",
                },
            },
            output_schema={
                "answer": "str - 综合回答",
                "sql": "str - 生成的只读 SQL",
                "results": "dict - 查询结果",
                "caliber_used": "str - 使用的口径",
            },
        )
        query.add_capability("metric_query", "基于语义口径的指标查询")
        query.add_capability("rag_search", "RAG 知识库检索")
        query.add_capability("data_analysis", "只读数据分析")
        query.add_capability("caliber_clarification", "口径澄清")
        query.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得执行写操作",
            "查询 Agent 只读，禁止任何写入/修改/删除",
        )
        query.add_constraint(
            ConstraintLevel.RED_LINE,
            "不得引用未定义口径",
            "引用未定义口径必须拒绝",
        )
        self._identities["query"] = query

    def get_identity(self, agent_type: str) -> AgentIdentity | None:
        """按类型查询 agent 身份。"""
        return self._identities.get(agent_type)

    def get_all_types(self) -> list[str]:
        """获取所有注册的 agent 类型。"""
        return list(self._identities.keys())

    def check_constraints(
        self, agent_type: str, action: str, context: dict[str, Any]
    ) -> list[str]:
        """检查某 agent 执行某操作的约束。返回红线违反列表。"""
        identity = self._identities.get(agent_type)
        if not identity:
            return [f"未知 agent 类型: {agent_type}"]
        return identity.validate_constraints(action, context)

    def register_custom(
        self,
        agent_type: str,
        name: str,
        description: str,
        capabilities: list[AgentCapability] | None = None,
        constraints: list[AgentConstraint] | None = None,
        **kwargs,
    ) -> AgentIdentity:
        """注册自定义 agent 身份。"""
        identity = AgentIdentity(
            agent_type=agent_type,
            name=name,
            description=description,
            capabilities=capabilities or [],
            constraints=constraints or [],
            **kwargs,
        )
        self._identities[agent_type] = identity
        return identity

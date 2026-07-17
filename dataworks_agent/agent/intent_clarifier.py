"""意图确认器 — SQL Agent 实践的意图确认机制。

实现：
- 对低置信度意图或模糊需求进行反问确认
- 支持必填字段缺失检测
- 确认通过后继续执行，未确认则阻断
- 参考 SQL Agent 的"意图确认 Agent"模式
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import Intent

logger = logging.getLogger(__name__)


class ConfirmationStatus:
    """确认状态。"""

    PENDING = "pending"  # 等待确认
    CONFIRMED = "confirmed"  # 已确认
    REJECTED = "rejected"  # 用户拒绝
    AUTO_CONFIRMED = "auto_confirmed"  # 高置信度自动确认


@dataclass
class ClarificationQuestion:
    """澄清问题。"""

    question: str  # 向用户提问
    field_name: str  # 对应缺失的参数字段
    hint: str = ""  # 提示示例
    required: bool = True  # 是否必填


@dataclass
class ConfirmationRequest:
    """确认请求。"""

    intent_action: str
    intent_confidence: float
    missing_fields: list[str]
    questions: list[ClarificationQuestion]
    status: str = ConfirmationStatus.PENDING
    user_answer: str = ""
    confirmed_at: str = ""

    def __post_init__(self):
        if not self.confirmed_at and self.status == ConfirmationStatus.CONFIRMED:
            self.confirmed_at = datetime.now(UTC).isoformat()


class IntentClarifier:
    """意图确认器 — 对模糊需求进行反问确认。

    参考 SQL Agent 实践：
    - 用户说"查询昨天积分第二名的代理商"可能存在二义性
    - 在生成 SQL 前，先确认用户真实意图
    - 对低置信度意图或必填字段缺失进行反问

    核心判断规则：
    - 置信度 >= 0.8 且无缺失字段 → 自动确认
    - 置信度 0.5-0.8 → 生成确认问题
    - 置信度 < 0.5 → 阻断，必须用户确认
    - 必填字段缺失 → 生成确认问题
    """

    # 需要意图确认的 action 类型（工作流类 action，非简单工具调用）
    CLARIFY_ACTIONS = {
        "forward_modeling",
        "ods_dwd_modeling",
        "agent_workflow",
        "reverse_modeling",
        "diagnose_issue",
        "metric_attribution",
    }

    # 按 action 类型定义必填字段
    REQUIRED_FIELDS: dict[str, list[str]] = {
        "forward_modeling": ["table_name", "source_table"],
        "create_table": ["table_name"],
        "ods_dwd_modeling": [],
        "agent_workflow": [],
        "metric_attribution": ["metric_id"],
        "diagnose_issue": [],
        "publish_review": ["table_name"],
        "query_lineage": ["table_name"],
        "create_node": ["table_name"],
        "reverse_modeling": ["table_name"],
    }

    # 确认问题模板
    QUESTION_TEMPLATES: dict[str, str] = {
        "table_name": "目标表名是什么？例如 dwd_trade_order_detail。",
        "source_table": "源表或主要输入表是什么？例如 ods_order。",
        "dwd_table": "DWD 目标表名是什么？例如 dwd_trade_order_detail。",
        "metric_id": "需要归因的指标或口径 ID 是什么？",
        "task_id": "需要诊断的任务 ID 是什么？",
        "datasource_name": "DataWorks 数据源名称是什么？例如 jky_singleshop。",
        "source_type": "ODS 来源类型是什么？可选 mysql、hologres、oss、realtime。",
    }

    def check_intent(
        self,
        intent: Intent,
        conversation_context: dict[str, Any] | None = None,
    ) -> ConfirmationRequest | None:
        """检查意图是否需要确认。

        只对工作流类 action 进行确认，简单工具调用（如 create_table）
        由下游 executor 自行处理缺失参数。

        确认条件（严格）：
        - 置信度 < 0.5 → 必须确认，否则阻断
        - 置信度 0.5-0.8 且有缺失字段 → 建议确认
        - 置信度 >= 0.8 → 不拦截，让下游 executor 处理

        参考 SQL Agent 实践：意图确认 Agent 只对存在二义性的问题生效，
        不拦截高置信度但参数不全的请求（下游 executor 已有澄清机制）。
        """
        # 只对需要确认的 action 类型进行检查
        if intent.action not in self.CLARIFY_ACTIONS:
            return None

        # 置信度 >= 0.8：下游 executor 处理缺失参数，不拦截
        if intent.confidence >= 0.8:
            return None

        # 置信度 0.5-0.8：有缺失字段时建议确认
        if intent.confidence >= 0.5:
            conversation_context = conversation_context or {}
            existing_params = conversation_context.get("params") or {}
            merged_params = {**existing_params, **intent.params}
            missing_fields = self._detect_missing_fields(intent, merged_params)
            if missing_fields:
                questions = self._build_questions(intent, missing_fields)
                if questions:
                    return ConfirmationRequest(
                        intent_action=intent.action,
                        intent_confidence=intent.confidence,
                        missing_fields=missing_fields,
                        questions=questions,
                    )
            return None

        # 置信度 < 0.5：必须确认
        conversation_context = conversation_context or {}
        existing_params = conversation_context.get("params") or {}
        merged_params = {**existing_params, **intent.params}
        missing_fields = self._detect_missing_fields(intent, merged_params)
        questions = self._build_questions(intent, missing_fields)
        if questions:
            return ConfirmationRequest(
                intent_action=intent.action,
                intent_confidence=intent.confidence,
                missing_fields=missing_fields,
                questions=questions,
            )
        return None

    def process_answer(
        self,
        request: ConfirmationRequest,
        user_answer: str,
    ) -> ConfirmationRequest:
        """处理用户回答。

        Returns:
            更新后的 ConfirmationRequest。
        """
        request.user_answer = user_answer

        # 检查是否提供了缺失字段
        if not request.questions:
            request.status = ConfirmationStatus.CONFIRMED
            return request

        # 简单启发式：如果用户回答了非空内容，视为确认
        if user_answer and user_answer.strip():
            request.status = ConfirmationStatus.CONFIRMED
        else:
            request.status = ConfirmationStatus.REJECTED

        return request

    def _has_missing_fields(self, intent: Intent, params: dict[str, Any]) -> list[str]:
        """检测缺失的必填字段。"""
        required = self.REQUIRED_FIELDS.get(intent.action, [])
        return [f for f in required if f not in params]

    def _detect_missing_fields(self, intent: Intent, params: dict[str, Any]) -> list[str]:
        """检测缺失字段。"""
        return self._has_missing_fields(intent, params)

    def _build_questions(
        self, intent: Intent, missing_fields: list[str]
    ) -> list[ClarificationQuestion]:
        """构建确认问题。"""
        questions = []
        for field_name in missing_fields:
            template = self.QUESTION_TEMPLATES.get(field_name, f"请补充: {field_name}")
            questions.append(
                ClarificationQuestion(
                    question=template,
                    field_name=field_name,
                    required=True,
                )
            )
        return questions

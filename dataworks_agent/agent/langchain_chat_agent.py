"""LangChain-based chat agent for DataWorks.
Replaces regex-based intent parsing with LLM-driven decision making.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from sqlalchemy import select

from dataworks_agent.agent.llm_intent_classifier import LLMIntent, LLMIntentClassifier
from dataworks_agent.config import settings
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ConversationHistoryModel
from dataworks_agent.llm.service import LLMService

logger = logging.getLogger(__name__)


class LangChainChatAgent:
    """基于 LangChain 的聊天 Agent。"""

    def __init__(self) -> None:
        # 使用现有的 LLM 服务
        self._llm_service = LLMService.from_settings(settings)
        self._intent_classifier = LLMIntentClassifier()
        self._prompt = self._create_prompt()

    def _save_message(self, conversation_id: str | None, role: str, content: str) -> None:
        """保存对话消息到数据库。"""
        if not conversation_id or not content:
            return
        try:
            session = SessionLocal()
            try:
                msg = ConversationHistoryModel(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                )
                session.add(msg)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("保存对话消息失败: %s", e)

    def _get_history(self, conversation_id: str | None, limit: int = 20) -> list[dict[str, str]]:
        """获取对话历史消息。"""
        if not conversation_id:
            return []
        try:
            session = SessionLocal()
            try:
                stmt = (
                    select(ConversationHistoryModel)
                    .where(ConversationHistoryModel.conversation_id == conversation_id)
                    .order_by(ConversationHistoryModel.id.desc())
                    .limit(limit)
                )
                result = session.execute(stmt)
                messages = result.scalars().all()
                return [{"role": msg.role, "content": msg.content} for msg in reversed(messages)]
            finally:
                session.close()
        except Exception as e:
            logger.warning("获取对话历史失败: %s", e)
            return []

    def _create_prompt(self) -> ChatPromptTemplate:
        """创建聊天 prompt。"""
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是一个数据仓库 Agent。
            你的职责是帮助用户完成数仓建模、任务诊断、血缘分析、指标归因等工作。
            能力范围：
            - 数据建模：帮助用户设计 ODS/DWD/DWS/DIM 表结构
            - 任务诊断：分析调度失败、数据异常等问题
            - 血缘分析：查看表/节点的上游依赖关系
            - 指标归因：分析指标波动的原因
            - 数据查询：基于语义口径的只读查询
            规则：
            1. 不要猜测生产口径，必须引用已定义的指标
            2. 涉及写操作时必须经过人工确认
            3. 对于模糊请求，先澄清再执行
            4. 保持专业、友好的语气""",
                ),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{input}"),
            ]
        )

    async def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        """处理聊天消息。"""
        try:
            # 保存用户消息到数据库
            self._save_message(conversation_id, "user", message)
            # 1. 先尝试 LLM 意图分类
            intent = await self._intent_classifier.classify(message)
            # 2. 根据意图决定下一步
            if intent.action == "greeting":
                response = self._handle_greeting(intent)
                self._save_message(conversation_id, "assistant", response["message"])
                return response
            elif intent.action == "clarification":
                response = self._handle_clarification(intent)
                self._save_message(conversation_id, "assistant", response["message"])
                return response
            elif intent.action == "ask_data":
                response = await self._handle_ask_data(intent)
                self._save_message(conversation_id, "assistant", response["message"])
                return response
            elif intent.action == "modeling":
                response = await self._handle_modeling(intent)
                self._save_message(conversation_id, "assistant", response["message"])
                return response
            elif intent.action == "diagnosis":
                response = await self._handle_diagnosis(intent)
                self._save_message(conversation_id, "assistant", response["message"])
                return response
            else:
                # 3. 如果意图不明，直接让 LLM 决定
                return await self._handle_unknown_intent(message, conversation_id)
        except Exception as e:
            logger.error("LangChain ChatAgent 处理失败: %s", e, exc_info=True)
            return {
                "message": f"处理失败：{e!s}",
                "success": False,
                "error": str(e),
            }

    def _handle_greeting(self, intent: LLMIntent) -> dict[str, Any]:
        """处理问候语。"""
        return {
            "message": "你好！我是 DataWorks Agent，可以帮助你完成数仓建模、任务诊断、血缘分析等工作。请告诉我你想要处理什么任务。",
            "success": True,
            "agent_mode": "greeting",
            "intent": intent,
        }

    def _handle_clarification(self, intent: LLMIntent) -> dict[str, Any]:
        """处理澄清请求。"""
        return {
            "message": "我需要更多信息才能帮助你。请明确说明你的目标表、源表或任务类型。",
            "success": False,
            "agent_mode": "needs_context",
            "intent": intent,
        }

    async def _handle_ask_data(self, intent: LLMIntent) -> dict[str, Any]:
        """处理数据查询请求。"""
        # TODO: 集成现有的 ask_data 工作流
        return {
            "message": "数据查询功能正在开发中...",
            "success": True,
            "agent_mode": "ask_data",
            "intent": intent,
        }

    async def _handle_modeling(self, intent: LLMIntent) -> dict[str, Any]:
        """处理建模请求。"""
        # TODO: 集成现有的 modeling 工作流
        return {
            "message": "建模功能正在开发中...",
            "success": True,
            "agent_mode": "modeling",
            "intent": intent,
        }

    async def _handle_diagnosis(self, intent: LLMIntent) -> dict[str, Any]:
        """处理诊断请求。"""
        # TODO: 集成现有的 diagnosis 工作流
        return {
            "message": "诊断功能正在开发中...",
            "success": True,
            "agent_mode": "diagnosis",
            "intent": intent,
        }

    async def _handle_unknown_intent(
        self, message: str, conversation_id: str | None = None
    ) -> dict[str, Any]:
        """处理未知意图 — 让 LLM 决定下一步。"""
        try:
            # 使用现有的 LLM 服务
            from dataworks_agent.llm.context import ContextBuilder
            from dataworks_agent.llm.service import LLMKeyMissingError

            # 获取历史消息
            history = self._get_history(conversation_id, limit=20)
            # 构建 LLM 上下文
            builder = ContextBuilder()
            builder.add_instruction("你是一个数据仓库 Agent。")
            # 添加历史消息到上下文
            for msg in history:
                if msg["role"] == "user":
                    builder.add_prompt(msg["content"])
                elif msg["role"] == "assistant":
                    builder.add_response(msg["content"])
            # 添加当前消息
            builder.add_prompt(message)
            context = builder.build()
            # 调用 LLM
            response = await self._llm_service.complete(context, "light")
            # 保存助手消息到数据库
            self._save_message(conversation_id, "assistant", response.content)
            return {
                "message": response.content,
                "success": True,
                "agent_mode": "llm_resolved",
            }
        except LLMKeyMissingError as e:
            logger.warning("LLM API key 未配置，回退到默认响应: %s", e)
            return {
                "message": "抱歉，我暂时无法理解你的请求。请尝试更具体的描述，比如'帮我建模 dwd_trade_order_detail'或'查看执行底座健康'。",
                "success": False,
                "agent_mode": "needs_context",
            }
        except Exception as e:
            logger.warning("LLM 决定下一步失败，回退到默认响应: %s", e)
            return {
                "message": "抱歉，我暂时无法理解你的请求。请尝试更具体的描述，比如'帮我建模 dwd_trade_order_detail'或'查看执行底座健康'。",
                "success": False,
                "agent_mode": "needs_context",
            }

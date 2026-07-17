"""LangChain-based intent classifier for DataWorks Agent.

Replaces regex-based intent parsing with LLM-driven understanding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMIntent:
    """LLM 解析的意图结果。"""

    action: str  # 动作类型
    confidence: float  # 置信度 0-1
    params: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    is_negated: bool = False
    reasoning: str = ""  # LLM 的思考过程


class LLMIntentClassifier:
    """基于 LLM 的意图分类器。"""

    def __init__(self) -> None:
        self._llm = self._create_llm()
        self._parser = JsonOutputParser()
        self._prompt = self._create_prompt()

    def _create_llm(self) -> ChatOpenAI:
        """创建 LLM 实例。"""
        return ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.llm_api_key or "dummy",  # 避免空密钥错误
            openai_api_base=settings.llm_base_url,
            temperature=0.1,  # 低温度确保一致性
        )

    def _create_prompt(self) -> ChatPromptTemplate:
        """创建意图分类 prompt。"""
        return ChatPromptTemplate.from_messages([
            (
                "system",
                """你是一个数据仓库 Agent 的意图理解器。
                用户输入可能是：
                1. 问候语（你好、hello 等）
                2. 模糊请求（你、这个等）
                3. 具体任务（建模、查询、诊断等）
                
                请分析用户意图并返回 JSON：
                {{
                    "action": "greeting" | "clarification" | "ask_data" | "modeling" | "diagnosis" | "unknown",
                    "confidence": 0.0-1.0,
                    "params": {{}},
                    "is_negated": false,
                    "reasoning": "简短分析"
                }}""",
            ),
            ("human", "{user_input}"),
        ])

    async def classify(self, text: str) -> LLMIntent:
        """分类用户输入。"""
        try:
            # 调用 LLM
            response = await self._llm.ainvoke(
                self._prompt.format_messages(user_input=text)
            )
            
            # 解析 JSON 响应
            result = self._parser.parse(response.content)
            
            return LLMIntent(
                action=result.get("action", "unknown"),
                confidence=result.get("confidence", 0.0),
                params=result.get("params", {}),
                raw_text=text,
                is_negated=result.get("is_negated", False),
                reasoning=result.get("reasoning", ""),
            )
        except Exception as e:
            logger.warning("LLM 意图分类失败: %s", e)
            # 回退到默认值
            return LLMIntent(
                action="unknown",
                confidence=0.0,
                raw_text=text,
                reasoning=f"LLM 调用失败: {str(e)}",
            )

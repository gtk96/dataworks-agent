"""RAG 上下文提供者 — 将检索结果注入 Agent 的意图理解和任务规划过程。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RAGContextProvider:
    """为 Agent 各阶段提供 RAG 增强的上下文。"""

    def __init__(self, retriever: KnowledgeRetriever) -> None:  # noqa: F821
        self._retriever = retriever

    async def enrich_intent_context(self, user_message: str) -> str:
        """在意图解析前注入相关规范上下文。"""
        context = await self._retriever.retrieve_for_intent(user_message)
        if context:
            logger.info("RAG intent context: %d snippets", context.count("\n- "))
        return context

    async def enrich_planning_context(self, task_type: str, params: dict[str, Any]) -> str:
        """在任务规划前注入相关规范上下文。"""
        context = await self._retriever.retrieve_for_planning(task_type, params)
        if context:
            logger.info("RAG planning context: %d snippets", context.count("\n- "))
        return context

    async def answer_question(self, question: str) -> str:
        """基于知识库回答事实性问题。"""
        results = await self._retriever.retrieve(question)
        if not results:
            return "未在知识库中找到相关内容。"
        lines = [f"基于知识库检索到以下相关信息（共 {len(results)} 条）：\n"]
        for idx, item in enumerate(results, start=1):
            source = item.metadata.get("source", "unknown")
            lines.append(f"**[{idx}] {source}** (score: {item.score:.2f})")
            lines.append(item.content[:500])
            lines.append("")
        return "\n".join(lines)

"""LangGraph-backed conversational context for clarification follow-ups."""

from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class ConversationState(TypedDict, total=False):
    incoming_message: str
    resolved_message: str
    pending_objective: str


class ConversationGraph:
    """Keep pending objectives in LangGraph checkpoints keyed by conversation id."""

    def __init__(self) -> None:
        builder = StateGraph(ConversationState)
        builder.add_node("resolve_context", self._resolve_context)
        builder.add_edge(START, "resolve_context")
        builder.add_edge("resolve_context", END)
        self._checkpointer = InMemorySaver()
        self._graph = builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _resolve_context(state: ConversationState) -> dict[str, str]:
        incoming = str(state.get("incoming_message") or "")
        pending = str(state.get("pending_objective") or "")
        if any(word in incoming for word in ("取消", "重新开始", "新任务")):
            return {"resolved_message": incoming, "pending_objective": ""}
        if pending:
            return {"resolved_message": f"{pending}\n补充信息：{incoming}"}
        return {"resolved_message": incoming}

    @staticmethod
    def _config(conversation_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": conversation_id}}

    async def resolve(self, message: str, conversation_id: str | None) -> str:
        if not conversation_id:
            return message
        state = await self._graph.ainvoke(
            {"incoming_message": message},
            config=self._config(conversation_id),
        )
        return str(state.get("resolved_message") or message)

    async def remember(
        self,
        conversation_id: str | None,
        objective: str,
        *,
        needs_clarification: bool,
    ) -> None:
        if not conversation_id:
            return
        await self._graph.aupdate_state(
            self._config(conversation_id),
            {"pending_objective": objective if needs_clarification else ""},
        )

    async def pending_objective(self, conversation_id: str) -> str:
        snapshot = await self._graph.aget_state(self._config(conversation_id))
        return str(snapshot.values.get("pending_objective") or "")

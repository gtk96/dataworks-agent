"""LangGraph-backed conversational state for recoverable follow-up interactions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
    PendingInteraction,
    resolve_interaction_answer,
)


class ConversationState(TypedDict, total=False):
    incoming_message: str
    resolved_message: str
    pending_objective: str
    objective: str
    action: str
    params: dict[str, Any]
    workflow_state: dict[str, Any]
    context_updates: dict[str, Any]
    selected_resources: dict[str, Any]
    pending_interaction: dict[str, Any]
    last_result: dict[str, Any]
    last_assistant_turn: dict[str, Any]
    conversation_summary: str
    query_frame: dict[str, Any]
    task_status: str
    state_version: int


class ConversationStateConflictError(RuntimeError):
    """Raised when a mutation targets an outdated conversation version."""

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("会话状态已经更新，请根据最新状态继续。")
        self.current = current


class ConversationGraph:
    """Keep structured workflow context in checkpoints keyed by conversation id."""

    def __init__(self, db_path: str = "data/conversation_checkpoints.db") -> None:
        self._db_path = db_path
        self._checkpointer: AsyncSqliteSaver | None = None
        self._graph = None
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._conversation_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _ensure_initialized(self) -> None:
        """Initialize the SQLite checkpointer and graph exactly once."""
        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            conn = await aiosqlite.connect(self._db_path)
            self._checkpointer = AsyncSqliteSaver(conn)
            await self._checkpointer.setup()
            builder = StateGraph(ConversationState)
            builder.add_node("resolve_context", self._resolve_context)
            builder.add_edge(START, "resolve_context")
            builder.add_edge("resolve_context", END)
            self._graph = builder.compile(checkpointer=self._checkpointer)
            self._initialized = True

    @staticmethod
    def _resolve_context(state: ConversationState) -> dict[str, Any]:
        incoming = str(state.get("incoming_message") or "")
        pending = str(state.get("pending_objective") or "")
        updates = dict(state.get("context_updates") or {})
        if any(
            word in incoming.lower() for word in ("取消", "重新开始", "新任务", "cancel", "reset")
        ):
            return {
                "resolved_message": incoming,
                "pending_objective": "",
                "objective": incoming,
                "action": "",
                "params": {},
                "workflow_state": {},
                "selected_resources": {},
                "pending_interaction": {},
                "last_result": {},
                "state_version": int(state.get("state_version") or 0) + 1,
            }
        objective = str(state.get("objective") or pending or incoming)
        resolved = (
            f"{objective}\n补充信息：{incoming}" if pending and incoming != objective else incoming
        )
        current_params = dict(state.get("params") or {})
        current_params.update(updates.get("params") or {})
        selected_resources = dict(state.get("selected_resources") or {})
        selected_resources.update(updates.get("selected_resources") or {})
        result: dict[str, Any] = {"resolved_message": resolved}
        if current_params:
            result["params"] = current_params
        if selected_resources:
            result["selected_resources"] = selected_resources
        if updates.get("workflow_state"):
            result["workflow_state"] = dict(updates["workflow_state"])
        if updates.get("action"):
            result["action"] = str(updates["action"])
        return result

    @staticmethod
    def _config(conversation_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": conversation_id}}

    async def resolve(
        self,
        message: str,
        conversation_id: str | None,
        *,
        context_updates: dict[str, Any] | None = None,
    ) -> str:
        if not conversation_id:
            return message
        await self._ensure_initialized()
        state = await self._graph.ainvoke(
            {"incoming_message": message, "context_updates": context_updates or {}},
            config=self._config(conversation_id),
        )
        return str(state.get("resolved_message") or message)

    async def context(self, conversation_id: str | None) -> dict[str, Any]:
        if not conversation_id:
            return {}
        await self._ensure_initialized()
        snapshot = await self._graph.aget_state(self._config(conversation_id))
        values = dict(snapshot.values or {})
        return {
            "objective": values.get("objective") or values.get("pending_objective") or "",
            "action": values.get("action") or "",
            "params": dict(values.get("params") or {}),
            "workflow_state": dict(values.get("workflow_state") or {}),
            "pending_objective": values.get("pending_objective") or "",
            "selected_resources": dict(values.get("selected_resources") or {}),
            "pending_interaction": dict(values.get("pending_interaction") or {}),
            "last_result": dict(values.get("last_result") or {}),
            "last_assistant_turn": dict(values.get("last_assistant_turn") or {}),
            "conversation_summary": str(values.get("conversation_summary") or ""),
            "query_frame": dict(values.get("query_frame") or {}),
            "task_status": str(values.get("task_status") or ""),
            "state_version": int(values.get("state_version") or 0),
        }

    async def remember(
        self,
        conversation_id: str | None,
        objective: str,
        *,
        needs_clarification: bool,
        action: str | None = None,
        params: dict[str, Any] | None = None,
        workflow_state: dict[str, Any] | None = None,
        pending_interaction: dict[str, Any] | None = None,
        selected_resources: dict[str, Any] | None = None,
        last_result: dict[str, Any] | None = None,
        last_assistant_turn: dict[str, Any] | None = None,
        conversation_summary: str | None = None,
        query_frame: dict[str, Any] | None = None,
        task_status: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not conversation_id:
            return {}
        await self._ensure_initialized()
        async with self._conversation_locks[conversation_id]:
            current = await self.context(conversation_id)
            current_version = int(current.get("state_version") or 0)
            if expected_version is not None and expected_version != current_version:
                raise ConversationStateConflictError(current=current)

            next_version = current_version + 1
            root_objective = str(current.get("objective") or objective)
            pending_payload = (
                dict(pending_interaction)
                if pending_interaction is not None
                else dict(current.get("pending_interaction") or {})
                if needs_clarification
                else {}
            )
            if pending_payload:
                pending_payload["state_version"] = next_version
            await self._graph.aupdate_state(
                self._config(conversation_id),
                {
                    "objective": root_objective,
                    "pending_objective": root_objective if needs_clarification else "",
                    "action": action or current.get("action") or "",
                    "params": dict(params or current.get("params") or {}),
                    "workflow_state": dict(workflow_state or current.get("workflow_state") or {}),
                    "pending_interaction": pending_payload,
                    "selected_resources": dict(
                        selected_resources
                        if selected_resources is not None
                        else current.get("selected_resources") or {}
                    ),
                    "last_result": dict(
                        last_result if last_result is not None else current.get("last_result") or {}
                    ),
                    "last_assistant_turn": dict(
                        last_assistant_turn
                        if last_assistant_turn is not None
                        else current.get("last_assistant_turn") or {}
                    ),
                    "conversation_summary": str(
                        conversation_summary
                        if conversation_summary is not None
                        else current.get("conversation_summary") or ""
                    ),
                    "query_frame": dict(
                        query_frame if query_frame is not None else current.get("query_frame") or {}
                    ),
                    "task_status": str(
                        task_status if task_status is not None else current.get("task_status") or ""
                    ),
                    "state_version": next_version,
                },
                as_node="resolve_context",
            )
            return await self.context(conversation_id)

    async def answer(
        self, conversation_id: str | None, answer: InteractionAnswer
    ) -> dict[str, Any]:
        if not conversation_id:
            raise InteractionExpiredError("会话不存在，请重新开始。")
        await self._ensure_initialized()
        async with self._conversation_locks[conversation_id]:
            current = await self.context(conversation_id)
            pending_data = dict(current.get("pending_interaction") or {})
            if not pending_data:
                raise InteractionExpiredError("当前没有等待回答的问题。")
            pending = PendingInteraction.model_validate(pending_data)
            resolved = resolve_interaction_answer(pending, answer)

            params = dict(current.get("params") or {})
            params.update(resolved.get("params") or {})
            selected_resources = dict(current.get("selected_resources") or {})
            selected_resources.update(resolved.get("selected_resources") or {})
            next_version = int(current.get("state_version") or pending.state_version) + 1
            await self._graph.aupdate_state(
                self._config(conversation_id),
                {
                    "params": params,
                    "selected_resources": selected_resources,
                    "pending_interaction": {},
                    "pending_objective": "",
                    "state_version": next_version,
                },
                as_node="resolve_context",
            )
            return {**resolved, "state_version": next_version}

    async def cancel(self, conversation_id: str | None) -> dict[str, Any]:
        if not conversation_id:
            return {}
        await self._ensure_initialized()
        async with self._conversation_locks[conversation_id]:
            current = await self.context(conversation_id)
            next_version = int(current.get("state_version") or 0) + 1
            await self._graph.aupdate_state(
                self._config(conversation_id),
                {
                    "pending_objective": "",
                    "pending_interaction": {},
                    "task_status": "cancelled",
                    "state_version": next_version,
                },
                as_node="resolve_context",
            )
            return await self.context(conversation_id)

    async def pending_objective(self, conversation_id: str) -> str:
        return str((await self.context(conversation_id)).get("pending_objective") or "")

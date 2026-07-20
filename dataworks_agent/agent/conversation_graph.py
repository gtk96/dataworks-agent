"""LangGraph-backed conversational state for recoverable follow-up interactions."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, TypedDict
from weakref import WeakValueDictionary

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


_PROCESS_CONVERSATION_LOCKS: WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    WeakValueDictionary()
)
_PROCESS_CONVERSATION_LOCKS_GUARD = threading.Lock()


class ConversationGraph:
    """Keep structured workflow context in checkpoints keyed by conversation id."""

    def __init__(self, db_path: str = "data/conversation_checkpoints.db") -> None:
        self._db_path = db_path
        self._normalized_db_path = os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.expanduser(db_path)))
        )
        self._connection: aiosqlite.Connection | None = None
        self._checkpointer: AsyncSqliteSaver | None = None
        self._graph = None
        self._initialized = False
        self._initialization_lock = asyncio.Lock()

    def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        key = (self._normalized_db_path, conversation_id)
        with _PROCESS_CONVERSATION_LOCKS_GUARD:
            lock = _PROCESS_CONVERSATION_LOCKS.get(key)
            if lock is None:
                lock = asyncio.Lock()
                _PROCESS_CONVERSATION_LOCKS[key] = lock
            return lock

    async def _ensure_initialized(self) -> None:
        """Initialize the SQLite checkpointer and graph exactly once."""
        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            conn = await aiosqlite.connect(self._db_path)
            try:
                checkpointer = AsyncSqliteSaver(conn)
                await checkpointer.setup()
                builder = StateGraph(ConversationState)
                builder.add_node("resolve_context", self._resolve_context)
                builder.add_edge(START, "resolve_context")
                builder.add_edge("resolve_context", END)
                graph = builder.compile(checkpointer=checkpointer)
            except Exception:
                await conn.close()
                raise
            self._connection = conn
            self._checkpointer = checkpointer
            self._graph = graph
            self._initialized = True

    async def aclose(self) -> None:
        """Close the lazily opened SQLite connection, if any."""
        async with self._initialization_lock:
            conn = self._connection
            if conn is None:
                return
            self._connection = None
            self._checkpointer = None
            self._graph = None
            self._initialized = False
            await conn.close()

    @staticmethod
    def _is_reset_message(message: str) -> bool:
        return any(
            word in message.lower() for word in ("取消", "重新开始", "新任务", "cancel", "reset")
        )

    @classmethod
    def _resolve_context(cls, state: ConversationState) -> dict[str, Any]:
        incoming = str(state.get("incoming_message") or "")
        pending = str(state.get("pending_objective") or "")
        updates = dict(state.get("context_updates") or {})
        if cls._is_reset_message(incoming):
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
        async with self._conversation_lock(conversation_id):
            return await self._resolve_unlocked(message, conversation_id, context_updates)

    async def _resolve_unlocked(
        self,
        message: str,
        conversation_id: str,
        context_updates: dict[str, Any] | None = None,
    ) -> str:
        if self._is_reset_message(message):
            await self._reset_unlocked(message, conversation_id, context_updates)
            return message
        state = await self._graph.ainvoke(
            {"incoming_message": message, "context_updates": context_updates or {}},
            config=self._config(conversation_id),
        )
        return str(state.get("resolved_message") or message)

    async def _reset_unlocked(
        self,
        message: str,
        conversation_id: str,
        context_updates: dict[str, Any] | None = None,
    ) -> None:
        current = await self._context_unlocked(conversation_id)
        await self._graph.aupdate_state(
            self._config(conversation_id),
            {
                "incoming_message": message,
                "context_updates": context_updates or {},
                "resolved_message": message,
                "pending_objective": "",
                "objective": "",
                "action": "",
                "params": {},
                "workflow_state": {},
                "selected_resources": {},
                "pending_interaction": {},
                "last_result": {},
                "last_assistant_turn": {},
                "conversation_summary": "",
                "query_frame": {},
                "task_status": "idle",
                "state_version": int(current.get("state_version") or 0) + 1,
            },
            as_node="resolve_context",
        )

    async def start_goal(self, conversation_id: str | None, objective: str) -> dict[str, Any]:
        """Start a new active goal without leaking state from the previous task."""
        if not conversation_id:
            return {}
        await self._ensure_initialized()
        async with self._conversation_lock(conversation_id):
            current = await self._context_unlocked(conversation_id)
            next_version = int(current.get("state_version") or 0) + 1
            await self._graph.aupdate_state(
                self._config(conversation_id),
                {
                    "objective": objective,
                    "pending_objective": "",
                    "action": "",
                    "params": {},
                    "workflow_state": {},
                    "selected_resources": {},
                    "pending_interaction": {},
                    "last_result": {},
                    "last_assistant_turn": {},
                    "conversation_summary": "",
                    "query_frame": {},
                    "task_status": "active",
                    "state_version": next_version,
                },
                as_node="resolve_context",
            )
            return await self._context_unlocked(conversation_id)

    async def context(self, conversation_id: str | None) -> dict[str, Any]:
        if not conversation_id:
            return {}
        await self._ensure_initialized()
        return await self._context_unlocked(conversation_id)

    async def _context_unlocked(self, conversation_id: str) -> dict[str, Any]:
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
        async with self._conversation_lock(conversation_id):
            current = await self._context_unlocked(conversation_id)
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
                    "action": (action if action is not None else current.get("action") or ""),
                    "params": dict(params if params is not None else current.get("params") or {}),
                    "workflow_state": dict(
                        workflow_state
                        if workflow_state is not None
                        else current.get("workflow_state") or {}
                    ),
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
            return await self._context_unlocked(conversation_id)

    async def answer(
        self, conversation_id: str | None, answer: InteractionAnswer
    ) -> dict[str, Any]:
        if not conversation_id:
            raise InteractionExpiredError("会话不存在，请重新开始。")
        await self._ensure_initialized()
        async with self._conversation_lock(conversation_id):
            current = await self._context_unlocked(conversation_id)
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
        async with self._conversation_lock(conversation_id):
            return await self._cancel_unlocked(conversation_id)

    async def _cancel_unlocked(self, conversation_id: str) -> dict[str, Any]:
        current = await self._context_unlocked(conversation_id)
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
        return await self._context_unlocked(conversation_id)

    async def pending_objective(self, conversation_id: str) -> str:
        return str((await self.context(conversation_id)).get("pending_objective") or "")

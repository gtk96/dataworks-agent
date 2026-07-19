"""Agent API routes for chat-oriented DataWorks operations."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.agent.interaction import InteractionAnswer
from dataworks_agent.agent.run_models import RunEvent
from dataworks_agent.runtime.publish_gate import PublishGate, PublishRequest
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

_agent = ChatAgent()


class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self._connections):
            await connection.send_json(message)


manager = ConnectionManager()


class ChatRequest(BaseModel):
    """Chat request."""

    message: str = Field(min_length=1, max_length=10000, description="User message")
    request_type: str | None = Field(default=None, description="Optional request type override")
    execution_mode: Literal["auto", "plan", "dev_execute"] = "plan"
    initialize_data: bool = True
    publish: bool = False
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    interaction_answer: InteractionAnswer | None = None
    context_updates: dict[str, Any] | None = Field(
        default=None, description="Structured answer from a clarification action"
    )


class ChatResponse(BaseModel):
    """Chat response."""

    message: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PublishReviewRequest(BaseModel):
    """人工发布审批输入。"""

    reviewer: str = Field(default="web-user", min_length=1, max_length=128)
    comment: str = Field(default="", max_length=1000)


def _publish_gate() -> PublishGate:
    gate = getattr(app_state, "_publish_gate", None)
    if gate is None:
        gate = PublishGate()
        app_state._publish_gate = gate
    return gate


def _publish_request_payload(request: PublishRequest) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "session_id": request.session_id,
        "table_name": request.table_name,
        "change_type": request.change_type,
        "status": request.status,
        "reviewer": request.reviewer,
        "reviewed_at": request.reviewed_at,
        "review_comment": request.review_comment,
        "deployment_status": request.deployment_status,
        "deployment_node_ids": request.deployment_node_ids,
        "deployment_error": request.deployment_error,
        "deployed_at": request.deployed_at,
        "created_at": request.created_at,
    }


def _conversation_envelope(conversation_id: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "active_goal": str(context.get("objective") or ""),
        "action": str(context.get("action") or ""),
        "status": str(context.get("task_status") or "idle"),
        "state_version": int(context.get("state_version") or 0),
        "selected_resources": dict(context.get("selected_resources") or {}),
    }


async def _response_data_with_conversation(
    response: Any, conversation_id: str | None
) -> dict[str, Any]:
    data = dict(response.data or {})
    if not conversation_id or isinstance(data.get("conversation"), dict):
        return data
    try:
        context = await _agent.get_conversation_context(conversation_id)
    except Exception:
        logger.warning("Failed to supplement conversation envelope", exc_info=True)
        return data
    data["conversation"] = _conversation_envelope(conversation_id, context)
    if (
        response.error == "interaction_expired"
        and not data.get("interaction")
        and context.get("pending_interaction")
    ):
        data["interaction"] = dict(context["pending_interaction"])
    return data


async def _execute_chat(
    payload: ChatRequest,
    *,
    client_ip: str,
    run_event_sink: Any | None = None,
) -> Any:
    workflow_options_explicit = bool(
        {"execution_mode", "initialize_data", "publish"} & payload.model_fields_set
    )
    if not workflow_options_explicit:
        kwargs: dict[str, Any] = {
            "execution_mode": "plan",
            "conversation_id": payload.conversation_id,
        }
        if payload.interaction_answer is not None:
            kwargs["interaction_answer"] = payload.interaction_answer
        if run_event_sink is not None:
            kwargs["run_event_sink"] = run_event_sink
        if payload.request_type is None:
            return await _agent.chat(payload.message, **kwargs)
        return await _agent.chat(payload.message, payload.request_type, **kwargs)

    kwargs = {
        "execution_mode": payload.execution_mode,
        "initialize_data": payload.initialize_data,
        "publish": payload.publish,
        "client_ip": client_ip,
        "conversation_id": payload.conversation_id,
    }
    if payload.context_updates is not None:
        kwargs["context_updates"] = payload.context_updates
    if payload.interaction_answer is not None:
        kwargs["interaction_answer"] = payload.interaction_answer
    if run_event_sink is not None:
        kwargs["run_event_sink"] = run_event_sink
    return await _agent.chat(payload.message, payload.request_type, **kwargs)


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Handle conversational planning and development execution."""
    logger.info("Received chat request: %s", payload.message[:50])
    client_ip = request.client.host if request.client else "127.0.0.1"
    response = await _execute_chat(payload, client_ip=client_ip)
    logger.info("Chat response: success=%s", response.success)
    response_data = await _response_data_with_conversation(response, payload.conversation_id)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response_data,
        error=response.error,
    )


@router.post("/runs/stream")
async def run_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream one authoritative Agent run as newline-delimited JSON."""

    client_ip = request.client.host if request.client else "127.0.0.1"

    async def event_generator():
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue()
        seen: set[str] = set()
        fallback_run_id = f"run_{uuid4().hex}"
        fallback_sequence = 0

        async def emit(event: RunEvent) -> None:
            seen.add(event.type)
            await queue.put(event)

        async def produce() -> None:
            nonlocal fallback_sequence
            try:
                response = await _execute_chat(
                    payload,
                    client_ip=client_ip,
                    run_event_sink=emit,
                )
                if "run.started" not in seen:
                    fallback_sequence += 1
                    await emit(
                        RunEvent(
                            "run.started",
                            fallback_run_id,
                            fallback_sequence,
                            {"conversation_id": payload.conversation_id or ""},
                        )
                    )
                if "response.completed" not in seen:
                    fallback_sequence += 1
                    await emit(
                        RunEvent(
                            "response.completed",
                            fallback_run_id,
                            fallback_sequence,
                            {
                                "response": {
                                    "message": response.message,
                                    "success": response.success,
                                    "data": await _response_data_with_conversation(
                                        response, payload.conversation_id
                                    ),
                                    "error": response.error,
                                }
                            },
                        )
                    )
            except Exception as exc:
                logger.exception("Agent run stream failed")
                fallback_sequence += 1
                await emit(
                    RunEvent(
                        "response.completed",
                        fallback_run_id,
                        fallback_sequence,
                        {
                            "response": {
                                "message": f"Agent 执行失败：{exc}",
                                "success": False,
                                "data": {"agent_mode": "recoverable_error"},
                                "error": "run_failed",
                            }
                        },
                    )
                )
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
                if await request.is_disconnected():
                    producer.cancel()
                    break
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    """Expose the Agent execution matrix used by the conversational workspace."""
    return {"capabilities": _agent.capability_status()}


@router.get("/messages")
async def get_messages(conversation_id: str, limit: int = 50) -> dict[str, Any]:
    """获取对话历史消息。"""
    messages = _agent.get_conversation_history(conversation_id, limit)
    context = await _agent.get_conversation_context(conversation_id)
    conversation = _conversation_envelope(conversation_id, context)
    return {
        "messages": messages,
        "active_interaction": context.get("pending_interaction") or None,
        "state_version": conversation["state_version"],
        "conversation": conversation,
    }


@router.get("/publish-gate/requests")
async def publish_requests() -> dict[str, Any]:
    """列出当前进程内等待人工处理的发布请求。"""
    requests = await _publish_gate().list_pending_requests()
    return {
        "requests": [_publish_request_payload(item) for item in requests],
        "total": len(requests),
    }


@router.post("/publish-gate/{request_id}/approve")
async def approve_publish_request(request_id: str, payload: PublishReviewRequest) -> dict[str, Any]:
    """人工批准后才调用 DataWorks 发布接口；失败时保留待审批以便重试。"""
    gate = _publish_gate()
    request = await gate.get_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="发布审批不存在")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail=f"发布审批已处理：{request.status}")

    node_ids = gate.extract_node_ids(request.payload)
    if not node_ids:
        raise HTTPException(status_code=422, detail="审批载荷中没有可发布的节点 UUID")
    node_client = getattr(app_state, "_node_client", None)
    if node_client is None:
        raise HTTPException(status_code=503, detail="DataWorks 节点发布通道未就绪")

    comment = payload.comment or f"Publish Gate {request.request_id} approved by {payload.reviewer}"
    try:
        deployed = bool(await node_client.deploy_nodes(node_ids, comment=comment))
        deploy_error = (
            "" if deployed else str(getattr(node_client, "last_error", "发布接口返回失败"))
        )
    except Exception as exc:
        logger.exception("Publish Gate deployment failed: %s", request_id)
        deployed = False
        deploy_error = str(exc)

    if not deployed:
        updated = await gate.record_deployment(
            request_id, node_ids, success=False, error=deploy_error or "发布失败"
        )
        return {
            "success": False,
            "message": f"发布失败，审批仍保持待处理：{deploy_error or '未知错误'}",
            "request": _publish_request_payload(updated or request),
        }

    approved = await gate.approve_request(request_id, payload.reviewer, payload.comment)
    updated = await gate.record_deployment(request_id, node_ids, success=True)
    return {
        "success": True,
        "message": f"已人工批准并发布 {len(node_ids)} 个节点。",
        "request": _publish_request_payload(updated or approved or request),
    }


@router.post("/publish-gate/{request_id}/reject")
async def reject_publish_request(request_id: str, payload: PublishReviewRequest) -> dict[str, Any]:
    """人工拒绝发布，不调用任何 DataWorks 发布接口。"""
    gate = _publish_gate()
    request = await gate.get_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="发布审批不存在")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail=f"发布审批已处理：{request.status}")
    rejected = await gate.reject_request(request_id, payload.reviewer, payload.comment)
    return {
        "success": True,
        "message": "已拒绝，节点仍为开发草稿，未发布。",
        "request": _publish_request_payload(rejected or request),
    }


@router.get("/status")
async def latest_status() -> dict[str, Any]:
    """Get the latest Agent task status."""
    status = _agent.get_status()
    return {"status": status}


@router.get("/status/{task_id}")
async def task_status(task_id: str) -> dict[str, Any]:
    """Get an Agent task status by task id."""
    status = _agent.get_status(task_id)
    return {"status": status}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket realtime chat endpoint."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            execution_mode = data.get("execution_mode", "plan")
            initialize_data = bool(data.get("initialize_data", True))
            publish = bool(data.get("publish", False))
            request_type = data.get("request_type")
            conversation_id = data.get("conversation_id")
            interaction_answer = (
                InteractionAnswer.model_validate(data["interaction_answer"])
                if data.get("interaction_answer") is not None
                else None
            )
            workflow_options_explicit = any(
                key in data for key in ("execution_mode", "initialize_data", "publish")
            )
            if not workflow_options_explicit and request_type is None:
                kwargs = {"conversation_id": conversation_id}
                if interaction_answer is not None:
                    kwargs["interaction_answer"] = interaction_answer
                response = await _agent.chat(message, **kwargs)
            else:
                kwargs: dict[str, Any] = {
                    "execution_mode": execution_mode,
                    "initialize_data": initialize_data,
                    "publish": publish,
                    "client_ip": websocket.client.host if websocket.client else "127.0.0.1",
                    "conversation_id": conversation_id,
                }
                if data.get("context_updates") is not None:
                    kwargs["context_updates"] = data["context_updates"]
                if interaction_answer is not None:
                    kwargs["interaction_answer"] = interaction_answer
                response = await _agent.chat(message, request_type, **kwargs)
            response_data = await _response_data_with_conversation(response, conversation_id)
            payload = {
                "message": response.message,
                "success": response.success,
                "data": response_data,
                "error": response.error,
            }
            await websocket.send_json({"type": "response", "data": payload})
            if response_data.get("status"):
                await websocket.send_json({"type": "status", "data": response_data["status"]})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket disconnected with error: %s", e)
        manager.disconnect(websocket)

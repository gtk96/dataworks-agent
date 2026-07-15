"""Agent API routes for chat-oriented DataWorks operations."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dataworks_agent.agent.core import ChatAgent
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
    context_updates: dict[str, Any] | None = Field(default=None, description="Structured answer from a clarification action")


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


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Handle conversational planning and development execution."""
    logger.info("Received chat request: %s", payload.message[:50])
    client_ip = request.client.host if request.client else "127.0.0.1"
    workflow_options_explicit = bool(
        {"execution_mode", "initialize_data", "publish"} & payload.model_fields_set
    )
    if not workflow_options_explicit:
        if payload.request_type is None:
            response = await _agent.chat(payload.message, conversation_id=payload.conversation_id)
        else:
            response = await _agent.chat(
                payload.message,
                payload.request_type,
                conversation_id=payload.conversation_id,
            )
    else:
        kwargs: dict[str, Any] = {
            "execution_mode": payload.execution_mode,
            "initialize_data": payload.initialize_data,
            "publish": payload.publish,
            "client_ip": client_ip,
            "conversation_id": payload.conversation_id,
        }
        if payload.context_updates is not None:
            kwargs["context_updates"] = payload.context_updates
        response = await _agent.chat(payload.message, payload.request_type, **kwargs)
    logger.info("Chat response: success=%s", response.success)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response.data,
        error=response.error,
    )


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    """Expose the Agent execution matrix used by the conversational workspace."""
    return {"capabilities": _agent.capability_status()}


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
            workflow_options_explicit = any(
                key in data for key in ("execution_mode", "initialize_data", "publish")
            )
            if not workflow_options_explicit and request_type is None:
                response = await _agent.chat(message, conversation_id=conversation_id)
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
                response = await _agent.chat(message, request_type, **kwargs)
            payload = {
                "message": response.message,
                "success": response.success,
                "data": response.data,
                "error": response.error,
            }
            await websocket.send_json({"type": "response", "data": payload})
            if response.data.get("status"):
                await websocket.send_json({"type": "status", "data": response.data["status"]})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket disconnected with error: %s", e)
        manager.disconnect(websocket)

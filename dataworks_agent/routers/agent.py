"""Agent API routes for chat-oriented DataWorks operations."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dataworks_agent.agent.core import ChatAgent

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


class ChatResponse(BaseModel):
    """Chat response."""

    message: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle chat messages for modeling, lineage query, and status check workflows."""
    logger.info("Received chat request: %s", request.message[:50])
    if request.request_type is None:
        response = await _agent.chat(request.message)
    else:
        response = await _agent.chat(request.message, request.request_type)
    logger.info("Chat response: success=%s", response.success)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response.data,
        error=response.error,
    )


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
            response = await _agent.chat(message)
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

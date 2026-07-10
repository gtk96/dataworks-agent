"""Agent API 路由 — 对话式数仓操作接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dataworks_agent.agent.core import ChatAgent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

_agent = ChatAgent()


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        for connection in self._connections:
            await connection.send_json(message)


manager = ConnectionManager()


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(min_length=1, max_length=10000, description="用户消息")


class ChatResponse(BaseModel):
    """聊天响应"""
    message: str
    success: bool
    data: dict = {}
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """处理聊天消息，支持数仓建模、血缘查询、状态检查等操作"""
    logger.info("收到聊天请求: %s", request.message[:50])
    response = await _agent.chat(request.message)
    logger.info("聊天响应: success=%s", response.success)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response.data,
        error=response.error,
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 实时通信端点"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            response = await _agent.chat(message)
            await websocket.send_json({
                "type": "response",
                "data": {
                    "message": response.message,
                    "success": response.success,
                    "data": response.data,
                },
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WS 异常断开: %s", e)
        manager.disconnect(websocket)

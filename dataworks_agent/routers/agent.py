"""Agent API 路由 — 对话式数仓操作接口。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from dataworks_agent.agent.core import ChatAgent

router = APIRouter(prefix="/agent", tags=["agent"])

_agent = ChatAgent()


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str


class ChatResponse(BaseModel):
    """聊天响应"""
    message: str
    success: bool
    data: dict = {}
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """处理聊天消息"""
    response = await _agent.chat(request.message)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response.data,
        error=response.error,
    )

"""Agent API 路由 — 对话式数仓操作接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from dataworks_agent.agent.core import ChatAgent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

_agent = ChatAgent()


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

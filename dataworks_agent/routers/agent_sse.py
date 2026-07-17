"""SSE streaming endpoint for real-time chat feedback."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from dataworks_agent.agent.core import ChatAgent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])
_agent = ChatAgent()


class StreamBuffer:
    """Async buffer for streaming events."""

    def __init__(self, maxsize: int = 64) -> None:
        self._queue: deque[str] = deque(maxlen=maxsize)
        self._ready = asyncio.Event()
        self._closed = False

    def push(self, event: str, data: dict) -> None:
        self._queue.append(json.dumps({"event": event, "data": data}))
        self._ready.set()

    def close(self) -> None:
        self._closed = True
        self._ready.set()

    async def pop(self) -> str | None:
        while True:
            if self._queue:
                return self._queue.popleft()
            if self._closed:
                return None
            self._ready.clear()
            await self._ready.wait()


_stream_buffers: dict[str, StreamBuffer] = {}


def _json_default(obj: object) -> object:
    """Best-effort fallback for non-JSON objects in SSE payloads."""
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return obj.to_dict()  # type: ignore[no-any-return]
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: v for k, v in vars(obj).items() if not k.startswith("_") and not callable(v)}
        except Exception:
            pass
    return str(obj)


def _safe_json_dumps(payload: dict) -> str:
    """Serialize SSE payload; never raise TypeError to the stream."""
    try:
        return json.dumps(payload, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        logger.exception("SSE payload JSON serialization failed: %s", exc)
        return json.dumps(
            {
                "type": "error",
                "message": f"结果序列化失败: {exc}",
            },
            ensure_ascii=False,
        )


def _sanitize_response_data(data: dict | None) -> dict:
    """Drop known non-JSON-safe / circular loop internals from agent payload."""
    if not isinstance(data, dict):
        return {}
    cleaned = dict(data)
    loop = cleaned.get("loop")
    if isinstance(loop, dict):
        # Keep summary metrics only — iterations historically held WorkflowResult objects.
        cleaned["loop"] = {
            "run_id": loop.get("run_id"),
            "objective": loop.get("objective"),
            "success": loop.get("success"),
            "stop_reason": loop.get("stop_reason"),
            "iteration_count": loop.get("iteration_count"),
            "best_score": loop.get("best_score"),
            "elapsed_ms": loop.get("elapsed_ms"),
            "runtime": loop.get("runtime"),
        }
    return cleaned


def _format_sse(data: str, event: str | None = None) -> str:
    """Format a single SSE frame."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    for line in data.split("\n"):
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


@router.get("/chat/stream")
async def chat_stream(request: Request) -> StreamingResponse:
    """SSE streaming endpoint for real-time chat.

    Query params:
        q: user message
        conversation_id: optional conversation ID
        execution_mode: auto | plan | dev_execute
    """
    q = request.query_params.get("q", "").strip()
    if not q:
        return StreamingResponse(
            iter([_format_sse(json.dumps({"error": "empty message"}))]),
            media_type="text/event-stream",
        )

    conversation_id = request.query_params.get("conversation_id") or str(uuid.uuid4())
    execution_mode = request.query_params.get("execution_mode", "auto")

    buffer = StreamBuffer()
    stream_id = str(uuid.uuid4())
    _stream_buffers[stream_id] = buffer

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield _format_sse(
                _safe_json_dumps(
                    {
                        "type": "connected",
                        "stream_id": stream_id,
                        "conversation_id": conversation_id,
                    }
                ),
                event="connect",
            )

            yield _format_sse(
                _safe_json_dumps(
                    {"type": "thinking", "message": "正在分析您的需求并制定执行路径..."}
                ),
                event="status",
            )

            try:
                response = await _agent.chat(
                    q,
                    execution_mode=execution_mode,
                    conversation_id=conversation_id,
                )
            except Exception as e:
                logger.exception("Agent chat failed")
                yield _format_sse(
                    _safe_json_dumps({"type": "error", "message": f"Agent 执行失败: {e}"}),
                    event="error",
                )
                return

            try:
                payload = {
                    "type": "response",
                    "message": response.message,
                    "success": response.success,
                    "data": _sanitize_response_data(response.data),
                    "error": response.error,
                    "conversation_id": conversation_id,
                }
                body = _safe_json_dumps(payload)
            except Exception as e:
                logger.exception("Failed to build SSE response payload")
                yield _format_sse(
                    _safe_json_dumps({"type": "error", "message": f"结果封装失败: {e}"}),
                    event="error",
                )
                return

            # If sanitizer fell back to an error envelope, surface it as error event.
            try:
                parsed = json.loads(body)
                event_name = "error" if parsed.get("type") == "error" else "response"
            except Exception:
                event_name = "response"
            yield _format_sse(body, event=event_name)

        finally:
            buffer.close()
            _stream_buffers.pop(stream_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/stream/{stream_id}/status")
async def stream_status(stream_id: str) -> dict:
    """Check if a stream is still alive."""
    alive = stream_id in _stream_buffers
    return {"stream_id": stream_id, "alive": alive}

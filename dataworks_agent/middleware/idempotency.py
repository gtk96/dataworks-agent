"""HTTP 请求幂等中间件 — X-Idempotency-Key 防重复提交。"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """幂等键管理 — 24h TTL，定时清理过期键。"""

    IDEMPOTENCY_TTL = 86400  # 24 小时

    def __init__(self, app):
        super().__init__(app)
        self._keys: dict[str, tuple[str, float]] = {}
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next):
        # 仅对 POST 请求检查幂等键
        if request.method != "POST":
            return await call_next(request)

        idempotency_key = request.headers.get("X-Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # 优先用 IPIsolationMiddleware 注入的 client_ip,否则回退到 socket peer
        client_ip = getattr(request.state, "client_ip", None) or (
            request.client.host if request.client else "unknown"
        )
        key = f"{client_ip}:{idempotency_key}"

        # 检查是否已存在
        existing = self._keys.get(key)
        if existing:
            task_id, ts = existing
            if time.time() - ts < self.IDEMPOTENCY_TTL:
                return JSONResponse(
                    status_code=200,
                    content={"task_id": task_id, "message": "重复请求，返回已有任务"},
                )
            else:
                del self._keys[key]

        # 先执行请求
        response = await call_next(request)

        # 自动 register: 如果响应是 JSON 且含 task_id 字段,写回缓存
        await self._auto_register_from_response(response, key)

        # 定时清理过期键
        self._cleanup_if_needed()

        return response

    async def _auto_register_from_response(self, response, key: str) -> None:
        """从响应 body 提取 task_id 并 register — 任何返回 {"task_id": "..."} 的 POST 端点自动防重复。"""
        try:
            media_type = getattr(response, "media_type", "") or ""
            if "json" not in media_type.lower():
                return
            body_bytes = b""
            # StreamingResponse 不会有 body,跳过
            if hasattr(response, "body_iterator") and not hasattr(response, "body"):
                return
            body = getattr(response, "body", None)
            if body is None:
                return
            if isinstance(body, bytes):
                body_bytes = body
            elif isinstance(body, str):
                body_bytes = body.encode()
            else:
                return
            import json as _json

            data = _json.loads(body_bytes)
            task_id = data.get("task_id") if isinstance(data, dict) else None
            if task_id:
                self._keys[key] = (str(task_id), time.time())
        except Exception:
            # 解析失败不影响主响应
            pass

    def register(self, key: str, ip: str, task_id: str) -> None:
        self._keys[f"{ip}:{key}"] = (task_id, time.time())

    def get_existing(self, key: str, ip: str) -> str | None:
        entry = self._keys.get(f"{ip}:{key}")
        if entry and (time.time() - entry[1] < self.IDEMPOTENCY_TTL):
            return entry[0]
        return None

    def _cleanup_if_needed(self) -> None:
        # 每 10 分钟清理一次
        now = time.time()
        if now - self._last_cleanup < 600:
            return
        self._last_cleanup = now
        expired = [k for k, v in self._keys.items() if now - v[1] > self.IDEMPOTENCY_TTL]
        for k in expired:
            del self._keys[k]

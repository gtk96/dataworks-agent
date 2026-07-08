"""权限分级中间件 — L0~L3 四级权限矩阵。"""

from __future__ import annotations

from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class PermissionManager:
    PERMISSIONS: ClassVar[dict] = {
        "L0": ["task:read", "history:read"],
        "L1": ["task:read", "task:create", "history:read", "sync:read"],
        "L2": [
            "task:read",
            "task:create",
            "history:read",
            "sync:read",
            "sync:execute",
            "schedule:modify",
        ],
        "L3": ["*"],
    }

    @classmethod
    def check(cls, level: str, action: str) -> bool:
        allowed = cls.PERMISSIONS.get(level, [])
        return "*" in allowed or action in allowed


class PermissionMiddleware(BaseHTTPMiddleware):
    """权限检查中间件 — 按路由 Path 映射到动作。"""

    # 路径 → 所需权限映射
    ACTION_MAP: ClassVar[dict] = {
        "POST /api/modeling/tasks": "task:create",
        "POST /api/sync/execute": "sync:execute",
        "POST /api/sync/diff": "sync:read",
        "GET /api/modeling/tasks": "task:read",
        "GET /api/sync/history": "history:read",
        "GET /api/logs": "history:read",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        action_key = f"{method} {path}"

        required = self.ACTION_MAP.get(action_key)
        if required is None:
            # 精确匹配未命中，尝试前缀匹配
            for pattern, action in self.ACTION_MAP.items():
                if method == pattern.split(" ")[0] and path.startswith(pattern.split(" ")[1]):
                    required = action
                    break

        if required:
            level = getattr(request.state, "permission_level", "L1")
            if not PermissionManager.check(level, required):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"权限不足: 需要 {required}，当前级别 {level}"},
                )

        return await call_next(request)

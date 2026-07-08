"""Token Bucket 限流器 — BFF(5QPS), CDP(3QPS), 每用户(10QPS)。"""

from __future__ import annotations

import asyncio
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class TokenBucket:
    """令牌桶限流算法。"""

    def __init__(self, rate: float, burst: int) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class RateLimiter:
    """多级限流器。"""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def create_bucket(self, key: str, rate: float, burst: int) -> None:
        self._buckets[key] = TokenBucket(rate=rate, burst=burst)

    async def acquire(self, key: str) -> bool:
        bucket = self._buckets.get(key)
        if bucket is None:
            return True
        return await bucket.acquire()


rate_limiter = RateLimiter()
rate_limiter.create_bucket("bff_api", 5, 10)
rate_limiter.create_bucket("cdp_ops", 3, 5)
rate_limiter.create_bucket("per_user", 10, 20)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按 IP 限流 — 命中 per_user 桶(10QPS, burst 20)返回 429。"""

    BUCKET = "per_user"

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not await rate_limiter.acquire(f"{self.BUCKET}:{client_ip}"):
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
            )
        return await call_next(request)

"""Observed capability health shared by the Agent page and system health API."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from dataworks_agent.api_clients.provider_errors import ProviderError
from dataworks_agent.config import settings
from dataworks_agent.eventlog.masking import mask_payload
from dataworks_agent.state import app_state


@dataclass(frozen=True)
class CapabilityState:
    configured: bool
    online: bool
    status: str
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityRegistry:
    """Run bounded read-only probes and cache one coherent snapshot."""

    def __init__(
        self,
        *,
        state: Any = app_state,
        settings_obj: Any = settings,
        llm_probe: Any | None = None,
        ttl_seconds: float = 15,
        timeout_seconds: float = 5,
    ) -> None:
        self._state = state
        self._settings = settings_obj
        self._llm_probe = llm_probe
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._cached_at = 0.0
        self._cached: dict[str, CapabilityState] = {}
        self._cached_fingerprint: tuple[Any, ...] = ()
        self._lock = asyncio.Lock()

    async def snapshot(self, *, force: bool = False) -> dict[str, CapabilityState]:
        now = time.monotonic()
        fingerprint = self._fingerprint()
        if (
            not force
            and self._cached
            and fingerprint == self._cached_fingerprint
            and now - self._cached_at < self._ttl_seconds
        ):
            return dict(self._cached)
        async with self._lock:
            now = time.monotonic()
            fingerprint = self._fingerprint()
            if (
                not force
                and self._cached
                and fingerprint == self._cached_fingerprint
                and now - self._cached_at < self._ttl_seconds
            ):
                return dict(self._cached)
            snapshot = await self._probe_all()
            self._cached = snapshot
            self._cached_at = now
            self._cached_fingerprint = fingerprint
            return dict(snapshot)

    async def snapshot_dict(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        snapshot = await self.snapshot(force=force)
        return {name: value.to_dict() for name, value in snapshot.items()}

    async def _probe_all(self) -> dict[str, CapabilityState]:
        bff = getattr(self._state, "_bff_client", None)
        cdp = getattr(self._state, "_cdp_client", None)
        openapi = getattr(self._state, "_openapi_client", None)
        maxcompute = getattr(self._state, "_maxcompute_client", None)
        llm_configured = bool(getattr(self._settings, "llm_api_key", ""))

        bff_state, cdp_state, openapi_state, maxcompute_state, llm_state = await asyncio.gather(
            self._probe("cookie_bff", bff is not None, lambda: self._probe_bff(bff)),
            self._probe("cdp_9222", cdp is not None, lambda: self._probe_cdp(cdp)),
            self._probe("openapi", openapi is not None, lambda: self._probe_openapi(openapi)),
            self._probe(
                "maxcompute",
                maxcompute is not None,
                lambda: self._probe_maxcompute(maxcompute),
            ),
            self._probe("llm", llm_configured, self._probe_llm),
        )
        checked_at = self._checked_at()
        aksk_configured = bool(
            getattr(self._settings, "aliyun_access_key_id", "")
            and getattr(self._settings, "aliyun_access_key_secret", "")
        )
        official = getattr(self._state, "_official_mcp_client", None)
        official_online = bool(
            official is not None and getattr(getattr(official, "status", None), "connected", False)
        )
        node_configured = getattr(self._state, "_node_client", None) is not None

        return {
            "agent_runtime": CapabilityState(True, True, "ready", checked_at),
            "ak_sk": CapabilityState(
                aksk_configured,
                aksk_configured and (openapi_state.online or maxcompute_state.online),
                "observed online"
                if openapi_state.online or maxcompute_state.online
                else "configured but no reachable AK/SK channel"
                if aksk_configured
                else "not configured",
                checked_at,
            ),
            "openapi": openapi_state,
            "maxcompute": maxcompute_state,
            "node_adapter": CapabilityState(
                node_configured,
                node_configured and openapi_state.online,
                "ready" if node_configured and openapi_state.online else "OpenAPI unavailable",
                checked_at,
            ),
            "cookie_bff": bff_state,
            "cdp_9222": cdp_state,
            "official_mcp": CapabilityState(
                official is not None,
                official_online,
                "connected" if official_online else "not connected",
                checked_at,
            ),
            "table_search": self._table_search_state(bff_state, maxcompute_state),
            "ida_query": CapabilityState(
                bff_state.configured,
                bff_state.online,
                "ready" if bff_state.online else "Cookie BFF unavailable",
                bff_state.checked_at,
            ),
            "llm": llm_state,
        }

    async def _probe(self, name: str, configured: bool, probe: Any) -> CapabilityState:
        checked_at = self._checked_at()
        if not configured:
            return CapabilityState(False, False, "not configured", checked_at)
        try:
            online = bool(await asyncio.wait_for(probe(), timeout=self._timeout_seconds))
            return CapabilityState(
                True,
                online,
                "ready" if online else "probe returned offline",
                checked_at,
            )
        except Exception as exc:
            return CapabilityState(True, False, self._safe_error(exc), checked_at)

    @staticmethod
    async def _probe_bff(client: Any) -> bool:
        if client is None:
            return False
        token = await client._refresh_csrf()
        if not token:
            return False
        await client.search_tables("__agent_health_probe_no_match__", page_size=1)
        return True

    @staticmethod
    async def _probe_cdp(client: Any) -> bool:
        return bool(client is not None and await client.test_connection())

    @staticmethod
    async def _probe_openapi(client: Any) -> bool:
        if client is None:
            return False
        await client.list_nodes(page_number=1, page_size=10)
        return True

    @staticmethod
    async def _probe_maxcompute(client: Any) -> bool:
        if client is None:
            return False
        entry = client._ensure_entry()
        project = await asyncio.to_thread(entry.get_project)
        return project is not None

    async def _probe_llm(self) -> bool:
        if self._llm_probe is not None:
            return bool(await self._llm_probe())
        if not getattr(self._settings, "llm_api_key", ""):
            return False
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=getattr(self._settings, "llm_base_url", ""),
            api_key=getattr(self._settings, "llm_api_key", ""),
        )
        await client.chat.completions.create(
            model=getattr(self._settings, "llm_model", ""),
            messages=[{"role": "user", "content": "health probe"}],
            max_tokens=1,
        )
        return True

    @staticmethod
    def _checked_at() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ProviderError):
            return exc.code
        return str(mask_payload(str(exc))).replace("\n", " ")[:200] or type(exc).__name__

    @staticmethod
    def _table_search_state(
        bff_state: CapabilityState,
        maxcompute_state: CapabilityState,
    ) -> CapabilityState:
        configured = bff_state.configured or maxcompute_state.configured
        online = bff_state.online or maxcompute_state.online
        if bff_state.online and maxcompute_state.online:
            status = "exact-name and free-text ready"
        elif maxcompute_state.online:
            status = f"exact-name ready; free-text unavailable: {bff_state.status}"
        elif bff_state.online:
            status = "free-text ready; exact-name MaxCompute unavailable"
        else:
            status = f"unavailable: {bff_state.status}"
        return CapabilityState(configured, online, status, bff_state.checked_at)

    def _fingerprint(self) -> tuple[Any, ...]:
        official = getattr(self._state, "_official_mcp_client", None)
        return (
            id(getattr(self._state, "_bff_client", None)),
            id(getattr(self._state, "_cdp_client", None)),
            id(getattr(self._state, "_openapi_client", None)),
            id(getattr(self._state, "_maxcompute_client", None)),
            id(getattr(self._state, "_node_client", None)),
            id(official),
            bool(getattr(getattr(official, "status", None), "connected", False)),
            bool(getattr(self._settings, "llm_api_key", "")),
            str(getattr(self._settings, "llm_model", "")),
        )


capability_registry = CapabilityRegistry()

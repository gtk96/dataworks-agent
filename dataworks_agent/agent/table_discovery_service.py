"""Provider-neutral, read-only table discovery routing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataworks_agent.agent.context.metadata_provider import MetadataProvider
from dataworks_agent.api_clients.provider_errors import (
    ProviderAuthenticationError,
    ProviderError,
)
from dataworks_agent.config import settings
from dataworks_agent.state import app_state

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNSET = object()


class DiscoveryStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DiscoveryResult:
    status: DiscoveryStatus
    provider: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error_code: str = ""


class TableDiscoveryService:
    """Choose an eligible read-only provider without overstating coverage."""

    def __init__(
        self,
        *,
        metadata_provider: Any | None = None,
        maxcompute: Any = _UNSET,
        projects: list[str] | None = None,
        state: Any = app_state,
    ) -> None:
        self.metadata_provider = metadata_provider or MetadataProvider()
        self._maxcompute = maxcompute
        self._state = state
        configured = [
            settings.maxcompute_project or settings.dataworks_dev_schema,
            settings.dataworks_prod_schema,
        ]
        self.projects = list(
            dict.fromkeys(project for project in (projects or configured) if project)
        )

    @property
    def maxcompute(self) -> Any | None:
        if self._maxcompute is not _UNSET:
            return self._maxcompute
        return getattr(self._state, "_maxcompute_client", None)

    async def search(self, keyword: str, message: str) -> DiscoveryResult:
        normalized = keyword.strip()
        exact_failures = 0
        maxcompute = self.maxcompute
        if _IDENTIFIER_RE.fullmatch(normalized) and maxcompute is not None:
            for project in self.projects:
                try:
                    exists = await maxcompute.table_exists(normalized, project=project)
                except Exception:
                    exact_failures += 1
                    continue
                if exists:
                    return DiscoveryResult(
                        status=DiscoveryStatus.FOUND,
                        provider="maxcompute",
                        candidates=[self._exact_candidate(project, normalized)],
                    )

        if (
            isinstance(self.metadata_provider, MetadataProvider)
            and getattr(self._state, "_bff_client", None) is None
        ):
            return DiscoveryResult(
                status=DiscoveryStatus.UNAVAILABLE,
                provider="cookie_bff",
                error_code="bff_not_configured",
            )

        try:
            result = await self.metadata_provider.search_table(normalized, message)
        except ProviderAuthenticationError as exc:
            return DiscoveryResult(
                status=DiscoveryStatus.AUTH_REQUIRED,
                provider=exc.provider,
                error_code=exc.code,
            )
        except ProviderError as exc:
            return DiscoveryResult(
                status=DiscoveryStatus.UNAVAILABLE,
                provider=exc.provider,
                error_code=exc.code,
            )
        except Exception:
            return DiscoveryResult(
                status=DiscoveryStatus.UNAVAILABLE,
                provider="cookie_bff",
                error_code="table_search_failed",
            )

        candidates = list(result.candidates if result is not None else [])
        if candidates:
            return DiscoveryResult(
                status=DiscoveryStatus.FOUND,
                provider="cookie_bff",
                candidates=candidates,
            )
        if exact_failures and _IDENTIFIER_RE.fullmatch(normalized):
            return DiscoveryResult(
                status=DiscoveryStatus.UNAVAILABLE,
                provider="maxcompute,cookie_bff",
                error_code="exact_search_incomplete",
            )
        return DiscoveryResult(status=DiscoveryStatus.NOT_FOUND, provider="cookie_bff")

    @staticmethod
    def _exact_candidate(project: str, table_name: str) -> dict[str, Any]:
        layer_match = re.search(r"(?:^|_)(ods|dim|dwd|dws|dmr)(?:_|$)", table_name, re.I)
        return {
            "project": project,
            "table_name": table_name,
            "full_name": f"{project}.{table_name}",
            "layer": layer_match.group(1).lower() if layer_match else "other",
            "comment": "",
            "entity_guid": f"odps.{project}.{table_name}",
            "provider": "maxcompute",
        }

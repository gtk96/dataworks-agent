"""Resolve DataWorks node parents without ever creating directories."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from dataworks_agent.services.ods_oss.directory_guard import (
    ExistingDirectoryEvidence,
    normalize_node_path,
)

PlacementStatus = Literal["resolved", "needs_context", "blocked"]
DirectoryReader = Callable[[str], ExistingDirectoryEvidence | Awaitable[ExistingDirectoryEvidence]]

_AD_REPORT_BASE = "????/106_????/MaxCompute/????"
_TEST_LAYER_PATHS = {
    "ODS": f"{_AD_REPORT_BASE}/00_ODS",
    "DIM": f"{_AD_REPORT_BASE}/01_DIM",
    "DWD": f"{_AD_REPORT_BASE}/02_DWD",
    "DWS": f"{_AD_REPORT_BASE}/03_DWS",
    "DMR": f"{_AD_REPORT_BASE}/04_DMR",
}


@dataclass(frozen=True)
class NodePlacementRequest:
    environment: str
    layer: str
    business_domain: str
    requested_path: str = ""
    candidate_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodePlacementDecision:
    status: PlacementStatus
    candidates: tuple[str, ...] = ()
    selected_path: str = ""
    evidence: tuple[ExistingDirectoryEvidence, ...] = ()
    reason: str = ""
    decision_id: str = field(default_factory=lambda: f"placement_{uuid4().hex[:12]}")
    creates_directory: bool = False


class NodePlacementPolicy:
    """Keep only candidate directories confirmed by fresh read-only evidence."""

    async def resolve(
        self,
        request: NodePlacementRequest,
        directory_reader: DirectoryReader,
    ) -> NodePlacementDecision:
        candidates = self._candidate_paths(request)
        if not candidates:
            return NodePlacementDecision(
                status="blocked",
                reason="???????????????????????????",
            )

        evidence: list[ExistingDirectoryEvidence] = []
        confirmed: list[str] = []
        for candidate in candidates:
            value = directory_reader(candidate)
            item = await value if inspect.isawaitable(value) else value
            evidence.append(item)
            if item.confirmed and item.is_fresh() and normalize_node_path(item.path) == candidate:
                confirmed.append(candidate)

        if len(confirmed) == 1:
            return NodePlacementDecision(
                status="resolved",
                candidates=tuple(confirmed),
                selected_path=confirmed[0],
                evidence=tuple(evidence),
                reason="?????????????????",
            )
        if len(confirmed) > 1:
            return NodePlacementDecision(
                status="needs_context",
                candidates=tuple(confirmed),
                evidence=tuple(evidence),
                reason="???????????????????????????",
            )
        missing = ", ".join(candidates)
        return NodePlacementDecision(
            status="blocked",
            candidates=tuple(candidates),
            evidence=tuple(evidence),
            reason=f"?????????????{missing}?????????????",
        )

    @staticmethod
    def _candidate_paths(request: NodePlacementRequest) -> tuple[str, ...]:
        environment = request.environment.strip().lower()
        layer = request.layer.strip().upper()
        requested = normalize_node_path(request.requested_path)
        supplied = tuple(
            dict.fromkeys(
                normalize_node_path(path)
                for path in request.candidate_paths
                if normalize_node_path(path)
            )
        )
        if environment in {"test", "testing"}:
            fixed = _TEST_LAYER_PATHS.get(layer, "")
            if not fixed:
                return ()
            if requested and requested != fixed:
                return ()
            return (fixed,)
        if requested:
            return tuple(dict.fromkeys((requested, *supplied)))
        return supplied

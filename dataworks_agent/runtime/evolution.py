"""语义自进化 — 检测新口径/别名/维度候选。

实现 Requirement 21：
- 检测新口径/别名/维度候选 → 产出演进提议供人确认
- 未确认不写单一事实源
- 行为进 Event_Log
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CandidateType(StrEnum):
    """候选类型。"""

    CALIBER = "caliber"  # 口径
    ALIAS = "alias"  # 别名
    DIMENSION = "dimension"  # 维度
    METRIC = "metric"  # 指标


class ProposalStatus(StrEnum):
    """提议状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class SemanticCandidate:
    """语义候选。"""

    candidate_id: str
    candidate_type: CandidateType
    key: str
    value: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # 来源（reverse_modeling / auto_detection / etc.）
    confidence: float = 0.0  # 置信度 0-1
    detected_at: str = ""

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(UTC).isoformat()


@dataclass
class EvolutionProposal:
    """演进提议。"""

    proposal_id: str
    candidates: list[SemanticCandidate] = field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    description: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class EvolutionResult:
    """演进结果。"""

    proposal_id: str
    success: bool
    applied_count: int = 0
    message: str = ""


class SemanticEvolver:
    """语义自进化器。

    检测新口径/别名/维度候选 → 产出演进提议供人确认。
    """

    def __init__(self) -> None:
        self._candidates: list[SemanticCandidate] = []
        self._proposals: list[EvolutionProposal] = []

    async def detect_candidates(
        self,
        source: str = "auto_detection",
    ) -> list[SemanticCandidate]:
        """检测候选。"""
        candidates = []

        # 简化实现：返回空列表
        # 实际应从数据中检测新口径/别名/维度
        logger.info("检测语义候选 (source=%s)", source)

        return candidates

    def create_proposal(
        self,
        candidates: list[SemanticCandidate],
        description: str = "",
    ) -> EvolutionProposal:
        """创建演进提议。"""
        import uuid

        proposal = EvolutionProposal(
            proposal_id=f"ep_{uuid.uuid4().hex[:8]}",
            candidates=candidates,
            description=description,
        )
        self._proposals.append(proposal)

        logger.info(
            "创建演进提议: %s (candidates=%d)",
            proposal.proposal_id,
            len(candidates),
        )

        return proposal

    async def approve_proposal(
        self,
        proposal_id: str,
    ) -> EvolutionResult:
        """批准演进提议。"""
        proposal = next(
            (p for p in self._proposals if p.proposal_id == proposal_id),
            None,
        )

        if not proposal:
            return EvolutionResult(
                proposal_id=proposal_id,
                success=False,
                message="提议不存在",
            )

        if proposal.status != ProposalStatus.PENDING:
            return EvolutionResult(
                proposal_id=proposal_id,
                success=False,
                message=f"提议状态不是 pending: {proposal.status.value}",
            )

        # 批准提议
        proposal.status = ProposalStatus.APPROVED

        # 应用候选到语义层
        applied_count = await self._apply_candidates(proposal.candidates)

        logger.info(
            "演进提议已批准: %s (applied=%d)",
            proposal_id,
            applied_count,
        )

        return EvolutionResult(
            proposal_id=proposal_id,
            success=True,
            applied_count=applied_count,
            message=f"已应用 {applied_count} 个候选",
        )

    async def reject_proposal(
        self,
        proposal_id: str,
        reason: str = "",
    ) -> EvolutionResult:
        """拒绝演进提议。"""
        proposal = next(
            (p for p in self._proposals if p.proposal_id == proposal_id),
            None,
        )

        if not proposal:
            return EvolutionResult(
                proposal_id=proposal_id,
                success=False,
                message="提议不存在",
            )

        proposal.status = ProposalStatus.REJECTED

        logger.info("演进提议已拒绝: %s (reason=%s)", proposal_id, reason)

        return EvolutionResult(
            proposal_id=proposal_id,
            success=True,
            message=f"提议已拒绝: {reason}",
        )

    async def _apply_candidates(
        self,
        candidates: list[SemanticCandidate],
    ) -> int:
        """应用候选到语义层。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        applied_count = 0

        for candidate in candidates:
            try:
                layer.upsert_definition(
                    kind=candidate.candidate_type.value,
                    key=candidate.key,
                    body=candidate.value,
                    actor="evolution",
                    source=candidate.source,
                )
                applied_count += 1
            except Exception as e:
                logger.warning("应用候选失败: %s: %s", candidate.key, e)

        return applied_count

    def list_proposals(
        self,
        status: ProposalStatus | None = None,
    ) -> list[EvolutionProposal]:
        """列出提议。"""
        if status:
            return [p for p in self._proposals if p.status == status]
        return self._proposals.copy()

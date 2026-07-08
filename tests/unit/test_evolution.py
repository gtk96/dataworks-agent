"""SemanticEvolver 单元测试 — 语义自进化。"""

import pytest

from dataworks_agent.runtime.evolution import (
    CandidateType,
    EvolutionProposal,
    EvolutionResult,
    ProposalStatus,
    SemanticCandidate,
    SemanticEvolver,
)


@pytest.fixture
def evolver():
    """创建 SemanticEvolver 实例。"""
    return SemanticEvolver()


@pytest.mark.asyncio
async def test_detect_candidates(evolver):
    """检测候选。"""
    candidates = await evolver.detect_candidates()
    assert isinstance(candidates, list)


def test_create_proposal(evolver):
    """创建演进提议。"""
    candidates = [
        SemanticCandidate(
            candidate_id="c_001",
            candidate_type=CandidateType.CALIBER,
            key="order_count",
            value={"caliber": "订单数量"},
        )
    ]
    proposal = evolver.create_proposal(candidates, "测试提议")

    assert proposal.proposal_id.startswith("ep_")
    assert len(proposal.candidates) == 1
    assert proposal.status == ProposalStatus.PENDING


@pytest.mark.asyncio
async def test_approve_proposal(evolver):
    """批准演进提议。"""
    candidates = [
        SemanticCandidate(
            candidate_id="c_001",
            candidate_type=CandidateType.CALIBER,
            key="test_metric",
            value={"caliber": "测试指标"},
        )
    ]
    proposal = evolver.create_proposal(candidates)

    result = await evolver.approve_proposal(proposal.proposal_id)

    assert result.success is True
    assert result.applied_count == 1


@pytest.mark.asyncio
async def test_reject_proposal(evolver):
    """拒绝演进提议。"""
    candidates = [
        SemanticCandidate(
            candidate_id="c_001",
            candidate_type=CandidateType.CALIBER,
            key="test_metric",
            value={"caliber": "测试指标"},
        )
    ]
    proposal = evolver.create_proposal(candidates)

    result = await evolver.reject_proposal(proposal.proposal_id, "不需要")

    assert result.success is True


@pytest.mark.asyncio
async def test_approve_nonexistent_proposal(evolver):
    """批准不存在的提议。"""
    result = await evolver.approve_proposal("ep_nonexistent")
    assert result.success is False
    assert "不存在" in result.message


def test_list_proposals(evolver):
    """列出提议。"""
    candidates = [
        SemanticCandidate(
            candidate_id="c_001",
            candidate_type=CandidateType.CALIBER,
            key="test_metric",
            value={},
        )
    ]
    evolver.create_proposal(candidates)
    evolver.create_proposal(candidates)

    proposals = evolver.list_proposals()
    assert len(proposals) == 2


@pytest.mark.asyncio
async def test_list_proposals_by_status(evolver):
    """按状态列出提议。"""
    candidates = [
        SemanticCandidate(
            candidate_id="c_001",
            candidate_type=CandidateType.CALIBER,
            key="test_metric",
            value={},
        )
    ]
    p1 = evolver.create_proposal(candidates)
    evolver.create_proposal(candidates)

    # 批准第一个
    await evolver.approve_proposal(p1.proposal_id)

    pending = evolver.list_proposals(status=ProposalStatus.PENDING)
    approved = evolver.list_proposals(status=ProposalStatus.APPROVED)

    assert len(pending) == 1
    assert len(approved) == 1


def test_semantic_candidate_post_init():
    """SemanticCandidate 初始化。"""
    candidate = SemanticCandidate(
        candidate_id="c_001",
        candidate_type=CandidateType.CALIBER,
        key="test",
    )
    assert candidate.detected_at != ""


def test_evolution_proposal_post_init():
    """EvolutionProposal 初始化。"""
    proposal = EvolutionProposal(proposal_id="ep_001")
    assert proposal.created_at != ""


def test_evolution_result_post_init():
    """EvolutionResult 初始化。"""
    result = EvolutionResult(proposal_id="ep_001", success=True)
    assert result.applied_count == 0

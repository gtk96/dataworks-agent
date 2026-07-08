"""SelfHealFlow 单元测试 — 自愈流程。"""

import pytest

from dataworks_agent.runtime.self_heal import (
    HealAction,
    HealProposal,
    HealResult,
    IssueReport,
    IssueType,
    SelfHealFlow,
)


@pytest.fixture
def flow():
    """创建 SelfHealFlow 实例。"""
    return SelfHealFlow()


@pytest.mark.asyncio
async def test_diagnose_schedule_failure(flow):
    """诊断调度失败。"""
    issue = IssueReport(
        issue_id="issue_001",
        issue_type=IssueType.SCHEDULE_FAILURE,
        source="scheduler",
        description="调度任务超时",
    )
    proposal = await flow.diagnose(issue)

    assert proposal.action == HealAction.RETRY
    assert proposal.requires_approval is False


@pytest.mark.asyncio
async def test_diagnose_data_anomaly(flow):
    """诊断数据异常。"""
    issue = IssueReport(
        issue_id="issue_002",
        issue_type=IssueType.DATA_ANOMALY,
        source="data_monitor",
        description="订单数量异常",
        context={"affected_tables": ["dwd_ord_order_day"]},
    )
    proposal = await flow.diagnose(issue)

    assert proposal.action == HealAction.FIX_DATA
    assert proposal.requires_approval is True


@pytest.mark.asyncio
async def test_diagnose_quality_issue(flow):
    """诊断质量问题。"""
    issue = IssueReport(
        issue_id="issue_003",
        issue_type=IssueType.QUALITY_ISSUE,
        source="quality_monitor",
        description="数据完整性不足",
    )
    proposal = await flow.diagnose(issue)

    assert proposal.action == HealAction.ALERT
    assert proposal.requires_approval is False


@pytest.mark.asyncio
async def test_diagnose_upstream_delay(flow):
    """诊断上游延迟。"""
    issue = IssueReport(
        issue_id="issue_004",
        issue_type=IssueType.UPSTREAM_DELAY,
        source="scheduler",
        description="上游任务未完成",
    )
    proposal = await flow.diagnose(issue)

    assert proposal.action == HealAction.WAIT
    assert proposal.requires_approval is False


@pytest.mark.asyncio
async def test_execute_retry(flow):
    """执行重试。"""
    proposal = HealProposal(
        proposal_id="hp_001",
        issue_id="issue_001",
        action=HealAction.RETRY,
    )
    result = await flow.execute(proposal)

    assert result.success is True


@pytest.mark.asyncio
async def test_execute_requires_approval(flow):
    """执行需要审批。"""
    proposal = HealProposal(
        proposal_id="hp_002",
        issue_id="issue_002",
        action=HealAction.FIX_DATA,
        requires_approval=True,
    )
    result = await flow.execute(proposal)

    assert result.success is False
    assert "审批" in result.message


def test_issue_report_post_init():
    """IssueReport 初始化。"""
    report = IssueReport(
        issue_id="issue_001",
        issue_type=IssueType.SCHEDULE_FAILURE,
    )
    assert report.detected_at != ""


def test_heal_proposal_post_init():
    """HealProposal 初始化。"""
    proposal = HealProposal(
        proposal_id="hp_001",
        issue_id="issue_001",
        action=HealAction.RETRY,
    )
    assert proposal.created_at != ""


def test_heal_result_post_init():
    """HealResult 初始化。"""
    result = HealResult(
        proposal_id="hp_001",
        success=True,
    )
    assert result.executed_at != ""

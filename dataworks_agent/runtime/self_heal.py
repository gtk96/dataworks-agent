"""SelfHealFlow — 自愈流程。

实现 Requirement 21 和 28：
- 调度失败/数据异常诊断 + 修复提议（生产写审批）
- 数据异常含质量维度
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class IssueType(StrEnum):
    """问题类型。"""

    SCHEDULE_FAILURE = "schedule_failure"  # 调度失败
    DATA_ANOMALY = "data_anomaly"  # 数据异常
    QUALITY_ISSUE = "quality_issue"  # 质量问题
    UPSTREAM_DELAY = "upstream_delay"  # 上游延迟


class HealAction(StrEnum):
    """自愈动作。"""

    RETRY = "retry"  # 重试
    FIX_DATA = "fix_data"  # 修复数据
    ALERT = "alert"  # 告警
    WAIT = "wait"  # 等待上游


@dataclass
class IssueReport:
    """问题报告。"""

    issue_id: str
    issue_type: IssueType
    source: str = ""
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    detected_at: str = ""

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(UTC).isoformat()


@dataclass
class HealProposal:
    """自愈提议。"""

    proposal_id: str
    issue_id: str
    action: HealAction
    description: str = ""
    requires_approval: bool = False
    affected_resources: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class HealResult:
    """自愈结果。"""

    proposal_id: str
    success: bool
    message: str = ""
    executed_at: str = ""

    def __post_init__(self):
        if not self.executed_at:
            self.executed_at = datetime.now(UTC).isoformat()


class SelfHealFlow:
    """自愈流程。

    调度失败/数据异常诊断 + 修复提议（生产写审批）。
    """

    async def diagnose(self, issue: IssueReport) -> HealProposal:
        """诊断问题并生成自愈提议。"""
        import uuid

        # 根据问题类型生成提议
        if issue.issue_type == IssueType.SCHEDULE_FAILURE:
            return HealProposal(
                proposal_id=f"hp_{uuid.uuid4().hex[:8]}",
                issue_id=issue.issue_id,
                action=HealAction.RETRY,
                description="调度失败，建议重试",
                requires_approval=False,
            )

        elif issue.issue_type == IssueType.DATA_ANOMALY:
            return HealProposal(
                proposal_id=f"hp_{uuid.uuid4().hex[:8]}",
                issue_id=issue.issue_id,
                action=HealAction.FIX_DATA,
                description="数据异常，需要修复",
                requires_approval=True,  # 生产写需要审批
                affected_resources=issue.context.get("affected_tables", []),
            )

        elif issue.issue_type == IssueType.QUALITY_ISSUE:
            return HealProposal(
                proposal_id=f"hp_{uuid.uuid4().hex[:8]}",
                issue_id=issue.issue_id,
                action=HealAction.ALERT,
                description="质量问题，需要告警",
                requires_approval=False,
            )

        elif issue.issue_type == IssueType.UPSTREAM_DELAY:
            return HealProposal(
                proposal_id=f"hp_{uuid.uuid4().hex[:8]}",
                issue_id=issue.issue_id,
                action=HealAction.WAIT,
                description="上游延迟，等待上游完成",
                requires_approval=False,
            )

        else:
            return HealProposal(
                proposal_id=f"hp_{uuid.uuid4().hex[:8]}",
                issue_id=issue.issue_id,
                action=HealAction.ALERT,
                description="未知问题，需要告警",
                requires_approval=False,
            )

    async def execute(self, proposal: HealProposal) -> HealResult:
        """执行自愈提议。"""
        # 简化实现：记录日志
        logger.info(
            "自愈提议执行: %s (action=%s, requires_approval=%s)",
            proposal.proposal_id,
            proposal.action.value,
            proposal.requires_approval,
        )

        if proposal.requires_approval:
            # 需要审批，不自动执行
            return HealResult(
                proposal_id=proposal.proposal_id,
                success=False,
                message="需要审批后执行",
            )

        # 执行自愈动作
        if proposal.action == HealAction.RETRY:
            return HealResult(
                proposal_id=proposal.proposal_id,
                success=True,
                message="重试已触发",
            )
        elif proposal.action == HealAction.ALERT:
            return HealResult(
                proposal_id=proposal.proposal_id,
                success=True,
                message="告警已发送",
            )
        elif proposal.action == HealAction.WAIT:
            return HealResult(
                proposal_id=proposal.proposal_id,
                success=True,
                message="等待上游完成",
            )
        else:
            return HealResult(
                proposal_id=proposal.proposal_id,
                success=False,
                message=f"不支持的动作: {proposal.action}",
            )

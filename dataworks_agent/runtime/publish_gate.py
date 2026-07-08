"""PublishGate — interrupt/resume 审批闸口。

实现 Requirement 14：生产写建模为 interrupt：Checkpoint 快照 + 变更载荷 + 权限上下文；Web 审批后 resume。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PublishRequest:
    """发布请求。"""

    request_id: str
    run_id: str
    session_id: str
    table_name: str
    change_type: str  # create / update / drop
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending / approved / rejected
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


class PublishGate:
    """发布审批闸口 — interrupt/resume 模式。

    生产写建模为 interrupt：Checkpoint 快照 + 变更载荷 + 权限上下文；
    Web 审批后 resume。
    """

    def __init__(self) -> None:
        self._pending_requests: dict[str, PublishRequest] = {}

    async def interrupt_for_approval(
        self,
        run_id: str,
        session_id: str,
        table_name: str,
        change_type: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PublishRequest:
        """中断运行，等待审批。"""
        import uuid

        request = PublishRequest(
            request_id=f"pub_{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            session_id=session_id,
            table_name=table_name,
            change_type=change_type,
            payload=payload,
            context=context or {},
        )

        self._pending_requests[request.request_id] = request

        # 记录日志
        logger.info(
            "发布审批请求已创建: %s (table=%s, type=%s)",
            request.request_id,
            table_name,
            change_type,
        )

        return request

    async def approve_request(
        self,
        request_id: str,
        reviewer: str,
        comment: str = "",
    ) -> PublishRequest | None:
        """批准发布请求。"""
        request = self._pending_requests.get(request_id)
        if not request:
            return None

        request.status = "approved"
        request.reviewer = reviewer
        request.reviewed_at = datetime.now(UTC).isoformat()
        request.review_comment = comment

        logger.info("发布请求已批准: %s (reviewer=%s)", request_id, reviewer)
        return request

    async def reject_request(
        self,
        request_id: str,
        reviewer: str,
        comment: str = "",
    ) -> PublishRequest | None:
        """拒绝发布请求。"""
        request = self._pending_requests.get(request_id)
        if not request:
            return None

        request.status = "rejected"
        request.reviewer = reviewer
        request.reviewed_at = datetime.now(UTC).isoformat()
        request.review_comment = comment

        logger.info("发布请求已拒绝: %s (reviewer=%s)", request_id, reviewer)
        return request

    async def get_request(self, request_id: str) -> PublishRequest | None:
        """获取发布请求。"""
        return self._pending_requests.get(request_id)

    async def list_pending_requests(self) -> list[PublishRequest]:
        """列出待审批请求。"""
        return [req for req in self._pending_requests.values() if req.status == "pending"]

    async def check_gate(self, table_name: str) -> dict[str, Any]:
        """检查发布门禁。"""
        from dataworks_agent.modeling.publish_gate import PublishGate as LegacyGate

        legacy_gate = LegacyGate()
        result = await legacy_gate.check(table_name)

        return {
            "passed": result.passed,
            "details": result.details,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    async def resume_after_approval(
        self,
        request_id: str,
    ) -> dict[str, Any] | None:
        """审批通过后恢复执行。"""
        request = self._pending_requests.get(request_id)
        if not request or request.status != "approved":
            return None

        # 返回恢复执行所需的信息
        return {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "table_name": request.table_name,
            "change_type": request.change_type,
            "payload": request.payload,
            "context": request.context,
            "approved_by": request.reviewer,
            "approved_at": request.reviewed_at,
        }

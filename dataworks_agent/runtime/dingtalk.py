"""DingTalk_Adapter — 钉钉群接入。

实现 Requirement 33 和 34：
- 群机器人接收 @机器人 → 解析 Anomaly_Report
- 信息不全会话内追问
- 只读结论回帖
- 发送者身份经 PermissionModel 归属
- 回帖按权限收敛不吐明细
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DingTalkMessage:
    """钉钉消息。"""

    message_id: str
    sender_id: str
    sender_name: str
    chat_id: str
    chat_type: str  # single / group
    content: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class DingTalkReply:
    """钉钉回复。"""

    message_id: str
    content: str
    at_users: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class DingTalkAdapter:
    """钉钉群接入适配器。

    群机器人接收 @机器人 → 解析 Anomaly_Report → 只读结论回帖。
    """

    def __init__(self) -> None:
        from dataworks_agent.auth.permission import Permission, PermissionModel, UserDirectory

        self.user_directory = UserDirectory()
        self.permission_model = PermissionModel()

        # 添加默认权限
        self.permission_model.add_permission(
            "default:viewer",
            Permission(resource="anomaly_report", action="read"),
        )

    async def handle_message(self, message: DingTalkMessage) -> DingTalkReply | None:
        """处理钉钉消息。"""
        # 1. 解析发送者身份
        user = self.user_directory.resolve_from_dingtalk(
            message.sender_id,
            {"name": message.sender_name},
        )

        # 2. 检查是否 @机器人
        if "@机器人" not in message.content and "@bot" not in message.content:
            return None  # 非 @机器人 消息，忽略

        # 3. 解析消息内容
        report = self._parse_anomaly_report(message.content)

        # 4. 检查权限

        perm_check = self.permission_model.check_permission(
            user,
            "anomaly_report",
            "read",
        )

        if not perm_check.allowed:
            return DingTalkReply(
                message_id=message.message_id,
                content=f"权限不足: {perm_check.reason}",
            )

        # 5. 处理异常报告
        if report:
            return await self._handle_anomaly_report(message, report, user)
        else:
            # 信息不全，追问
            return DingTalkReply(
                message_id=message.message_id,
                content="请提供异常指标名称和预期值，例如：@机器人 订单数量异常，预期 100，实际 200",
            )

    def _parse_anomaly_report(self, content: str) -> dict[str, Any] | None:
        """解析异常报告。"""
        # 简化实现：从消息内容提取指标信息
        # 实际应使用 NLP 或正则解析
        if "异常" in content:
            return {
                "metric_id": "parsed_metric",
                "expected_value": None,
                "actual_value": None,
            }
        return None

    async def _handle_anomaly_report(
        self,
        message: DingTalkMessage,
        report: dict[str, Any],
        user: Any,
    ) -> DingTalkReply:
        """处理异常报告。"""
        from dataworks_agent.runtime.attribution import AnomalyReport, MetricAttributor

        # 创建异常报告
        anomaly_report = AnomalyReport(
            report_id=f"ar_{message.message_id}",
            metric_id=report.get("metric_id", ""),
            expected_value=report.get("expected_value"),
            actual_value=report.get("actual_value"),
            context={"user_id": user.user_id, "team": user.team},
        )

        # 执行归因诊断
        attributor = MetricAttributor()
        result = await attributor.diagnose(anomaly_report)

        # 构建回复（只读结论，不吐明细）
        reply_content = self._build_reply_content(result, user)

        return DingTalkReply(
            message_id=message.message_id,
            content=reply_content,
            at_users=[message.sender_id],
        )

    def _build_reply_content(self, result: Any, user: Any) -> str:
        """构建回复内容（按权限收敛）。"""
        # 根据用户权限决定是否展示详细信息
        if user.role == "admin":
            # 管理员可以看到详细信息
            detail = f"\n根因: {result.root_cause.value if result.root_cause else '未知'}"
        else:
            # 普通用户只看结论
            detail = ""

        if result.resolved:
            return f"诊断完成: {result.explanation}{detail}"
        else:
            return f"诊断中: {result.explanation}"


async def send_dingtalk_message(
    webhook_url: str,
    content: str,
    at_users: list[str] | None = None,
) -> bool:
    """发送钉钉群消息。

    Args:
        webhook_url: 钉钉机器人 Webhook URL
        content: 消息内容
        at_users: 需要 @的用户列表

    Returns:
        是否发送成功
    """
    import httpx

    payload = {
        "msgtype": "text",
        "text": {
            "content": content,
            "at": {
                "atMobiles": at_users or [],
                "isAtAll": False,
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errcode") == 0:
                    logger.info("钉钉消息发送成功")
                    return True
                else:
                    logger.warning("钉钉消息发送失败: %s", data.get("errmsg"))
                    return False
            else:
                logger.warning("钉钉消息发送失败: HTTP %s", resp.status_code)
                return False
    except Exception as e:
        logger.error("钉钉消息发送异常: %s", e)
        return False


async def get_dingtalk_user_info(access_token: str, user_id: str) -> dict[str, Any] | None:
    """获取钉钉用户信息。

    Args:
        access_token: 钉钉访问令牌
        user_id: 用户 ID

    Returns:
        用户信息字典
    """
    import httpx

    url = f"https://oapi.dingtalk.com/v3/users/{user_id}"
    headers = {"x-acs-dingtalk-access-token": access_token}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errcode") == 0:
                    return data.get("result")
                else:
                    logger.warning("获取钉钉用户信息失败: %s", data.get("errmsg"))
                    return None
            else:
                logger.warning("获取钉钉用户信息失败: HTTP %s", resp.status_code)
                return None
    except Exception as e:
        logger.error("获取钉钉用户信息异常: %s", e)
        return None

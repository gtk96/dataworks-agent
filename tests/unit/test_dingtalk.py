"""DingTalkAdapter 单元测试 — 钉钉群接入。"""

import pytest

from dataworks_agent.runtime.dingtalk import DingTalkAdapter, DingTalkMessage, DingTalkReply


@pytest.fixture
def adapter():
    """创建 DingTalkAdapter 实例。"""
    return DingTalkAdapter()


@pytest.mark.asyncio
async def test_handle_message_not_at_bot(adapter):
    """处理消息 — 非 @机器人。"""
    message = DingTalkMessage(
        message_id="msg_001",
        sender_id="user_001",
        sender_name="张三",
        chat_id="chat_001",
        chat_type="group",
        content="这是一条普通消息",
    )
    result = await adapter.handle_message(message)
    assert result is None


@pytest.mark.asyncio
async def test_handle_message_at_bot(adapter):
    """处理消息 — @机器人。"""
    message = DingTalkMessage(
        message_id="msg_002",
        sender_id="user_001",
        sender_name="张三",
        chat_id="chat_001",
        chat_type="group",
        content="@机器人 订单数量异常",
    )
    result = await adapter.handle_message(message)

    assert result is not None
    assert isinstance(result, DingTalkReply)
    assert result.message_id == "msg_002"


@pytest.mark.asyncio
async def test_handle_message_no_report(adapter):
    """处理消息 — 信息不全，追问。"""
    message = DingTalkMessage(
        message_id="msg_003",
        sender_id="user_001",
        sender_name="张三",
        chat_id="chat_001",
        chat_type="group",
        content="@机器人 你好",
    )
    result = await adapter.handle_message(message)

    assert result is not None
    assert "请提供" in result.content


def test_parse_anomaly_report(adapter):
    """解析异常报告。"""
    content = "订单数量异常，预期 100，实际 200"
    report = adapter._parse_anomaly_report(content)
    assert report is not None
    assert "metric_id" in report


def test_parse_anomaly_report_no_anomaly(adapter):
    """解析异常报告 — 无异常。"""
    content = "今天天气不错"
    report = adapter._parse_anomaly_report(content)
    assert report is None


def test_dingtalk_message_post_init():
    """DingTalkMessage 初始化。"""
    message = DingTalkMessage(
        message_id="msg_001",
        sender_id="user_001",
        sender_name="张三",
        chat_id="chat_001",
        chat_type="group",
        content="test",
    )
    assert message.timestamp != ""


def test_dingtalk_reply_post_init():
    """DingTalkReply 初始化。"""
    reply = DingTalkReply(
        message_id="msg_001",
        content="test",
    )
    assert reply.timestamp != ""
    assert reply.at_users == []

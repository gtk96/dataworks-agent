"""回归测试: 'oss 数据源' / '数据源' 业务关键词应该被识别为 DataWorks 工作流目标。

历史症状: 用户输入 "我有个 oss 数据源" 时, IntentParser 返回 action="unknown",
导致 ChatAgent 走 _build_no_plan_response 输出"我不能映射"。修复方式:
DATAWORKS_GOAL_WORDS 加上 "oss" 和 "数据源", 让 _looks_like_dataworks_goal 命中,
返回 action="agent_workflow", 走 workflow_service._execute_standard_oss_flow。
"""

from __future__ import annotations

import pytest

from dataworks_agent.agent.nlu.intent_parser import IntentParser


@pytest.fixture
def parser() -> IntentParser:
    return IntentParser()


def test_oss_keyword_recognized_as_dataworks_goal(parser):
    """'我有个 oss 数据源' 应该被识别为 DataWorks 工作流目标。"""
    assert parser._looks_like_dataworks_goal("我有个 oss 数据源") is True


def test_datasource_keyword_recognized_as_dataworks_goal(parser):
    """单独 '数据源' 也应该被识别。"""
    assert parser._looks_like_dataworks_goal("我有一个数据源") is True


def test_pure_oss_path_recognized(parser):
    """OSS 路径形式 (oss://bucket/prefix) 也应该被识别。"""
    assert parser._looks_like_dataworks_goal("oss://bucket/prefix/") is True


def test_unrelated_text_not_recognized(parser):
    """无关文本不应被误识别。"""
    assert parser._looks_like_dataworks_goal("你好") is False
    assert parser._looks_like_dataworks_goal("hello") is False
    assert parser._looks_like_dataworks_goal("") is False


def test_parse_oss_datasource_returns_agent_workflow(parser):
    """完整 parse: '我有个 oss 数据源' → action='agent_workflow'。"""
    intent = parser.parse("我有个 oss 数据源")
    assert intent.action == "agent_workflow"
    assert intent.confidence > 0

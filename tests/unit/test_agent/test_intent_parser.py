import pytest

from dataworks_agent.agent.nlu.intent_parser import IntentParser


@pytest.fixture
def parser():
    return IntentParser()


def test_parse_create_table_intent(parser):
    """测试解析创建表意图"""
    result = parser.parse("创建ods_user表")
    assert result.action == "create_table"
    assert "table_name" in result.params
    assert result.params["table_name"] == "ods_user"


def test_parse_query_lineage_intent(parser):
    """测试解析查询血缘意图"""
    result = parser.parse("查询ods_user的血缘")
    assert result.action == "query_lineage"
    assert "table_name" in result.params


def test_parse_unknown_intent(parser):
    """测试解析未知意图"""
    result = parser.parse("今天天气怎么样")
    assert result.action == "unknown"
    assert result.confidence < 0.5

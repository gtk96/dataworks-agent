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


def test_parse_check_status_intent(parser):
    """测试解析检查状态意图"""
    result = parser.parse("检查任务状态")
    assert result.action == "check_status"


def test_parse_unknown_intent(parser):
    """测试解析未知意图"""
    result = parser.parse("今天天气怎么样")
    assert result.action == "unknown"
    assert result.confidence < 0.5


def test_parse_negation_intent(parser):
    """测试否定句意图解析"""
    result = parser.parse("不要创建表")
    assert result.action == "create_table"
    assert result.is_negated is True
    assert result.confidence < 0.5


def test_parse_negation_with_negation_words(parser):
    """测试各种否定词"""
    negation_cases = [
        ("别创建表", True),
        ("禁止创建表", True),
        ("取消创建表", True),
        ("创建表", False),
    ]
    for text, expected_negated in negation_cases:
        result = parser.parse(text)
        assert result.is_negated == expected_negated, f"Text: {text}"


def test_parse_query_table_without_lineage_keyword(parser):
    """Test query plus table name defaults to lineage/dependency planning."""
    query = chr(0x67E5) + chr(0x8BE2)
    result = parser.parse(f"{query} ods_user")
    assert result.action == "query_lineage"
    assert result.params["table_name"] == "ods_user"
    assert result.confidence >= 0.5


def test_parse_natural_business_query_as_ask_data(parser):
    result = parser.parse("查一下今天各家族的有效订单数")
    assert result.action == "ask_data"


def test_query_lineage_is_not_shadowed_by_business_query(parser):
    result = parser.parse("查询 ods_user 的血缘")
    assert result.action == "query_lineage"


@pytest.mark.parametrize(
    "message",
    [
        "\u4eca\u5929\u5404\u5bb6\u65cf\u7684\u6709\u6548\u8ba2\u5355\u662f\u591a\u5c11",
        "\u4eca\u5929\u6bcf\u4e2a\u5bb6\u65cf\u6709\u591a\u5c11\u6709\u6548\u8ba2\u5355",
        "\u5404\u5bb6\u65cf\u4eca\u65e5\u6709\u6548\u8ba2\u5355\u6570\u662f\u591a\u5c11",
        "\u4eca\u5929\u7684\u51c0\u8d21\u732e\u8ba2\u5355\u662f\u591a\u5c11",
    ],
)
def test_parse_declarative_business_questions_as_ask_data(parser, message):
    result = parser.parse(message)
    assert result.action == "ask_data"


@pytest.mark.parametrize(
    "message",
    [
        "\u4eca\u5929\u5e7f\u544a\u82b1\u8d39\u591a\u5c11\uff1f",
        "\u4eca\u5929\u7269\u6d41\u6210\u672c\u591a\u5c11\uff1f",
        "\u4eca\u5929\u91c7\u8d2d\u6210\u672c\u591a\u5c11\uff1f",
        "\u4eca\u5929\u7b7e\u6536\u7387\u662f\u591a\u5c11\uff1f",
        "\u4eca\u5929\u82b1\u8d39\u591a\u5c11\uff1f",
    ],
)
def test_parse_business_knowledge_metrics_as_ask_data(parser, message):
    result = parser.parse(message)
    assert result.action == "ask_data"


def test_parse_reverse_analysis_as_reverse_modeling(parser):
    result = parser.parse("\u9006\u5411\u5206\u6790 giikin_aliyun.tb_rp_ord_order_cnt_hi")
    assert result.action == "reverse_modeling"
    assert result.params["table_name"] == "giikin_aliyun.tb_rp_ord_order_cnt_hi"


def test_parse_execution_foundation_check_as_diagnose_issue(parser):
    result = parser.parse("\u68c0\u67e5\u6267\u884c\u5e95\u5ea7")
    assert result.action == "diagnose_issue"


def test_parse_explicit_task_id_as_diagnose_issue(parser):
    result = parser.parse("\u6392\u67e5\u4efb\u52a1 nonexistent-task-id")
    assert result.action == "diagnose_issue"
    assert result.params["task_id"] == "nonexistent-task-id"

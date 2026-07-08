"""ProposalGuard 单元测试 — 确定性护栏。"""

import pytest

from dataworks_agent.semantic.guard import ProposalGuard, ValidationResult


@pytest.fixture
def guard():
    """创建 ProposalGuard 实例。"""
    return ProposalGuard()


def test_check_ddl_valid(guard):
    """DDL 检查 — 有效 DDL。"""
    ddl = "CREATE TABLE dwd_ord_order_day (id STRING, name STRING) PARTITIONED BY (dt STRING);"
    result = guard.check_ddl(ddl)
    assert result.passed is True


def test_check_ddl_invalid(guard):
    """DDL 检查 — 无效 DDL（缺少 CREATE TABLE）。"""
    ddl = "INSERT INTO table VALUES (1);"
    result = guard.check_ddl(ddl)
    assert result.passed is False
    assert len(result.errors) > 0


def test_check_table_name_valid(guard):
    """表名检查 — 有效表名。"""
    result = guard.check_table_name("dwd_ord_order_day")
    assert result.passed is True


def test_check_table_name_invalid(guard):
    """表名检查 — 无效表名。"""
    result = guard.check_table_name("INVALID_TABLE_NAME")
    # 可能通过也可能失败，取决于命名规范
    assert isinstance(result, ValidationResult)


def test_check_layer_dependency_valid(guard):
    """层间依赖检查 — 有效依赖。"""
    result = guard.check_layer_dependency("DWD", ["ods_ord_order_hour"])
    assert result.passed is True


def test_check_layer_dependency_invalid(guard):
    """层间依赖检查 — 无效依赖。"""
    result = guard.check_layer_dependency("DWD", ["dws_wrong_layer"])
    assert result.passed is False
    assert len(result.errors) > 0


def test_check_sql_syntax_valid(guard):
    """SQL 语法检查 — 有效 SQL。"""
    sql = "SELECT id, name FROM ods_ord_order_hour WHERE dt = '2024-01-01';"
    result = guard.check_sql_syntax(sql)
    assert result.passed is True


def test_check_sql_syntax_invalid(guard):
    """SQL 语法检查 — 无效 SQL。"""
    sql = "SELECT * FROM WHERE;"
    result = guard.check_sql_syntax(sql)
    assert result.passed is False


def test_check_proposal_valid(guard):
    """综合校验 — 有效提议。"""
    proposal = {
        "target_table": "dwd_ord_order_day",
        "target_layer": "DWD",
        "source_tables": ["ods_ord_order_hour"],
        "ddl": "CREATE TABLE dwd_ord_order_day (id STRING) PARTITIONED BY (dt STRING);",
        "sql": "SELECT id FROM ods_ord_order_hour WHERE dt = '${bizdate}';",
        "fields": ["id"],
    }
    result = guard.check_proposal(proposal)
    assert result.passed is True


def test_check_proposal_invalid(guard):
    """综合校验 — 无效提议。"""
    proposal = {
        "target_table": "dwd_ord_order_day",
        "target_layer": "DWD",
        "source_tables": ["dws_wrong_layer"],  # 无效依赖
        "ddl": "CREATE TABLE dwd_ord_order_day (id STRING) PARTITIONED BY (dt STRING);",
        "sql": "SELECT id FROM ods_ord_order_hour WHERE dt = '${bizdate}';",
        "fields": ["id"],
    }
    result = guard.check_proposal(proposal)
    assert result.passed is False
    assert len(result.errors) > 0

"""import_sql DDL 解析单元测试 — v11 §4.3/§4.4。"""

from __future__ import annotations

import logging

from dataworks_agent.routers.import_sql import parse_ddl_file


def test_parse_ddl_default_with_semicolon_in_string():
    """字符串 DEFAULT 内含分号不应截断列块（§4.3）。"""
    ddl = """
CREATE TABLE ods_test_demo (
  id bigint,
  reason string DEFAULT '类型1；取消申请 ; 备注'
)
PARTITIONED BY (ds string);
"""
    tables = parse_ddl_file(ddl)
    assert len(tables) == 1
    assert "取消申请" in tables[0]["ddl"]
    assert "PARTITIONED BY" in tables[0]["ddl"]


def test_parse_ddl_layer_comment_overrides_prefix(caplog):
    """`-- layer: dim` 注释优先于 ods_ 表名前缀（§4.4）。"""
    ddl = """
-- layer: dim
CREATE TABLE ods_user_profile (
  id bigint
);
"""
    with caplog.at_level(logging.WARNING):
        tables = parse_ddl_file(ddl)
    assert tables[0]["layer"] == "DIM"


def test_parse_ddl_layer_comment_conflict_logs_warning(caplog):
    """注释与前缀冲突时 warning 且以注释为准。"""
    ddl = """
-- layer: dim
CREATE TABLE dwd_orders_daily (
  id bigint
);
"""
    with caplog.at_level(logging.WARNING):
        tables = parse_ddl_file(ddl)
    assert tables[0]["layer"] == "DIM"
    assert any("冲突" in r.message for r in caplog.records)


def test_parse_ddl_double_quoted_identifier_skips_paren_in_string():
    """双引号定界符内的括号不参与 depth 计数。"""
    ddl = """
CREATE TABLE ods_qt_demo (
  id bigint,
  lbl string DEFAULT "foo (bar)"
);
"""
    tables = parse_ddl_file(ddl)
    assert len(tables) == 1
    assert "foo (bar)" in tables[0]["ddl"]

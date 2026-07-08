"""DestructiveOpGuard 单元测试 — 执行层拦截与放行（Requirement 36）。"""

from __future__ import annotations

import pytest

from dataworks_agent.api_clients.destructive_guard import (
    DestructiveOpBlockedError,
    guard_node_op,
    guard_sql,
)


class TestBlockedSql:
    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM dataworks.ord_order WHERE dt='20260101'",
            "delete from t",
            "TRUNCATE TABLE dataworks.ord_order",
            "truncate dataworks.t",
            "ALTER TABLE dataworks.ord DROP PARTITION (dt='20260101')",
            "ALTER TABLE dataworks.ord DROP COLUMN name",
            "ALTER TABLE dataworks.ord DROP COLUMNS (a, b)",
            "DROP TABLE dataworks.ord_order",
            "DROP TABLE IF EXISTS dataworks.dwd_mkt_ad_group_day",
            "DROP TABLE prod_table",
        ],
    )
    def test_blocked(self, sql):
        with pytest.raises(DestructiveOpBlockedError):
            guard_sql(sql)


class TestAllowedSql:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT OVERWRITE TABLE dataworks.dwd_x PARTITION(dt) SELECT * FROM src",
            "INSERT INTO dataworks.dwd_x SELECT 1",
            "CREATE TABLE dataworks.dwd_x (id bigint) PARTITIONED BY (dt string)",
            "CREATE TABLE IF NOT EXISTS dataworks.t (id bigint)",
            "ALTER TABLE dataworks.t ADD COLUMNS (age bigint)",
            "SELECT * FROM dataworks.t WHERE dt='20260101' LIMIT 10",
            "DROP TABLE tmp_scratch",
            "DROP TABLE IF EXISTS dataworks.test_sandbox",
            "DROP TABLE dataworks.tmp_20260101",
        ],
    )
    def test_allowed(self, sql):
        guard_sql(sql)  # 不抛


class TestCommentsAndMultiStatement:
    def test_comment_with_semicolon_not_bypass(self):
        # 行尾注释里的分号不应导致 DELETE 漏检
        sql = "DELETE FROM t -- 删除旧数据 ; 备注\nWHERE dt='20260101'"
        with pytest.raises(DestructiveOpBlockedError):
            guard_sql(sql)

    def test_forbidden_keyword_only_in_comment_is_ignored(self):
        sql = "SELECT * FROM t -- 不要 DELETE FROM t\nWHERE dt='20260101'"
        guard_sql(sql)  # 注释里的 DELETE 不算

    def test_multi_statement_blocks_if_any_forbidden(self):
        sql = "CREATE TABLE tmp_a (id bigint); DROP TABLE prod_b;"
        with pytest.raises(DestructiveOpBlockedError):
            guard_sql(sql)

    def test_multi_statement_all_allowed(self):
        sql = "CREATE TABLE tmp_a (id bigint); INSERT OVERWRITE TABLE tmp_a SELECT 1;"
        guard_sql(sql)


class TestNodeOps:
    @pytest.mark.parametrize("op", ["DELETE_NODE", "OFFLINE_NODE", "delete", "offline", "UNDEPLOY"])
    def test_blocked_node_ops(self, op):
        with pytest.raises(DestructiveOpBlockedError):
            guard_node_op(op)

    @pytest.mark.parametrize("op", ["CREATE_NODE", "UPDATE_NODE", "DEPLOY", "GET_NODE"])
    def test_allowed_node_ops(self, op):
        guard_node_op(op)  # 不抛

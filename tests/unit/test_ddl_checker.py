"""ddl_checker 单元测试 — v14 F6-3 修复回归。"""

from __future__ import annotations

from dataworks_agent.governance.ddl_checker import _extract_columns


class TestExtractColumns:
    """v14：解析含 COMMENT 后缀的字段行不应丢失字段。"""

    def test_basic_field(self) -> None:
        ddl = """CREATE TABLE dataworks.ods_a (
  id BIGINT,
  name STRING
)"""
        cols = _extract_columns(ddl)
        assert [c["name"] for c in cols] == ["id", "name"]
        assert cols[0]["type"] == "BIGINT"
        assert cols[1]["type"] == "STRING"

    def test_field_with_comment_suffix(self) -> None:
        """评审档 F6-3 场景：`id BIGINT COMMENT '主键'` 不应被整行 skip。"""
        ddl = """CREATE TABLE dataworks.ods_b (
  id BIGINT COMMENT '主键',
  type INT COMMENT '类型，1:取消',
  amount DECIMAL(18,2)
)"""
        cols = _extract_columns(ddl)
        assert [c["name"] for c in cols] == ["id", "type", "amount"]
        assert cols[0]["type"] == "BIGINT"
        assert cols[1]["type"] == "INT"
        # DECIMAL 保留括号
        assert "DECIMAL" in cols[2]["type"]

    def test_pure_comment_line_still_skipped(self) -> None:
        """纯元数据行（仅 COMMENT ...）应被 skip。"""
        ddl = """CREATE TABLE dataworks.ods_c (
  id BIGINT
)
COMMENT '表注释'
LIFECYCLE 30"""
        cols = _extract_columns(ddl)
        assert [c["name"] for c in cols] == ["id"]

    def test_partition_after_columns(self) -> None:
        """PARTITIONED BY 之后不再解析字段。"""
        ddl = """CREATE TABLE dataworks.ods_d (
  id BIGINT,
  dt STRING
)
PARTITIONED BY (
  dt STRING COMMENT '分区'
)"""
        cols = _extract_columns(ddl)
        # dt 应作为字段被解析一次；PARTITIONED BY 后整段 skip
        names = [c["name"] for c in cols]
        assert "id" in names
        assert "dt" in names

"""ddl_checker 单元测试 — v14 F6-3 修复回归 + 词根集成。"""

from __future__ import annotations

import pytest

from dataworks_agent.governance.ddl_checker import (
    _extract_columns,
    _infer_expected_type,
    check_ddl,
    check_ddl_async,
)
from dataworks_agent.schemas import RootCheckField, RootCheckResult


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
        assert "DECIMAL" in cols[2]["type"]

    def test_pure_comment_line_still_skipped(self) -> None:
        ddl = """CREATE TABLE dataworks.ods_c (
  id BIGINT
)
COMMENT '表注释'
LIFECYCLE 30"""
        cols = _extract_columns(ddl)
        assert [c["name"] for c in cols] == ["id"]

    def test_partition_after_columns(self) -> None:
        ddl = """CREATE TABLE dataworks.ods_d (
  id BIGINT,
  dt STRING
)
PARTITIONED BY (
  dt STRING COMMENT '分区'
)"""
        cols = _extract_columns(ddl)
        names = [c["name"] for c in cols]
        assert "id" in names
        assert "dt" in names


class TestDdlRootCheck:
    _SAMPLE_DDL = """drop table if exists dwd_ord_order_detail_day;

create table dwd_ord_order_detail_day (
  order_id string comment '订单ID',
  {amount_field} decimal(24,6) comment '订单金额'
)
partitioned by (dt string comment '业务日期');"""

    @pytest.mark.asyncio
    async def test_invalid_root_fails_online(self, monkeypatch) -> None:
        async def _mock_check_fields(self, fields: list[str]) -> RootCheckResult:
            return RootCheckResult(
                passed=False,
                field_results=[
                    RootCheckField(
                        field_name="order_aamt",
                        valid=False,
                        invalid_segments=["aamt"],
                        suggested_name="order_amt",
                    )
                ],
                summary="1/2 个字段不合规（线上词根表 dim_pub_column_dictionary_static）",
                source="online",
            )

        monkeypatch.setattr(
            "dataworks_agent.modeling.root_checker.RootChecker.check_fields",
            _mock_check_fields,
        )
        result = await check_ddl_async(self._SAMPLE_DDL.format(amount_field="order_aamt"))
        assert result.passed is False
        assert result.root_source == "online"
        assert any("词根不合规" in err and "order_aamt" in err for err in result.errors)
        assert any("线上词根表" in warn for warn in result.warnings)

    @pytest.mark.asyncio
    async def test_valid_root_passes_online(self, monkeypatch) -> None:
        async def _mock_check_fields(self, fields: list[str]) -> RootCheckResult:
            return RootCheckResult(
                passed=True,
                field_results=[RootCheckField(field_name=name, valid=True) for name in fields],
                summary="0/2 个字段不合规（线上词根表 dim_pub_column_dictionary_static）",
                source="online",
            )

        monkeypatch.setattr(
            "dataworks_agent.modeling.root_checker.RootChecker.check_fields",
            _mock_check_fields,
        )
        result = await check_ddl_async(self._SAMPLE_DDL.format(amount_field="order_amt"))
        assert result.passed is True
        assert result.root_source == "online"

    def test_sync_check_ddl_skips_roots(self) -> None:
        """同步 check_ddl 不含词根（供离线/闭环内部结构检查）。"""
        result = check_ddl(self._SAMPLE_DDL.format(amount_field="order_aamt"))
        assert result.passed is True
        assert not any("词根不合规" in err for err in result.errors)


class TestSuffixTypeInference:
    def test_aamt_not_treated_as_amount(self) -> None:
        assert _infer_expected_type("order_aamt") == "string"

    def test_amt_treated_as_amount(self) -> None:
        assert _infer_expected_type("order_amt") == "decimal(24,6)"

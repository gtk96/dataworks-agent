"""Unit tests for native Chinese table lookup helpers (data-mcp style)."""

from __future__ import annotations

import pytest

from dataworks_agent.agent.workflow_service import AgentWorkflowService


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("查一下订单表", "订单"),
        ("查询销售表有多少条", "销售"),
        ("看看广告消耗表", "广告消耗"),
    ],
)
def test_extract_table_search_keyword(message: str, expected: str) -> None:
    assert AgentWorkflowService._extract_table_search_keyword(message, {}) == expected


def test_looks_like_physical_table() -> None:
    assert AgentWorkflowService._looks_like_physical_table("dwd_trade_order_detail")
    assert AgentWorkflowService._looks_like_physical_table("giikin.ods_order")
    assert not AgentWorkflowService._looks_like_physical_table("订单")
    assert not AgentWorkflowService._looks_like_physical_table("订单表")


def test_user_wants_non_ods_default() -> None:
    assert AgentWorkflowService._user_wants_non_ods("查一下订单表") is True
    assert AgentWorkflowService._user_wants_non_ods("看看销售表") is True


def test_user_wants_non_ods_with_marker() -> None:
    assert AgentWorkflowService._user_wants_non_ods("看 ods 订单") is False
    assert AgentWorkflowService._user_wants_non_ods("查订单贴源") is False


def test_partition_columns_for_giikin_aliyun() -> None:
    cols = AgentWorkflowService._partition_columns_for(
        "giikin_aliyun.tb_ods_ord_gk_third_order_return_di"
    )
    assert cols == ("pt",)


def test_partition_columns_for_giikin_hour_table() -> None:
    assert AgentWorkflowService._partition_columns_for(
        "giikin.dwd_trade_order_hour"
    ) == ("dt", "ht")
    assert AgentWorkflowService._partition_columns_for(
        "giikin.dwd_trade_order_day"
    ) == ("dt",)
    assert AgentWorkflowService._partition_columns_for(
        "giikin_develop.tmp_test_hourly"
    ) == ("dt", "ht")


def test_format_partition_clause_uses_ht_zero() -> None:
    sql = AgentWorkflowService._format_partition_clause(("dt", "ht"), None)
    assert sql == " WHERE dt='20260716' AND ht='00'" or " WHERE dt='2" in sql
    # The ht value must be '00' (data-mcp / project convention) and dt must
    # be a yyyymmdd 8-digit string.
    import re as _re
    m = _re.match(r" WHERE dt='(\d{8})' AND ht='(\d{2})'", sql)
    assert m is not None
    assert m.group(2) == "00"
    assert len(m.group(1)) == 8


def test_build_simple_table_sql_count() -> None:
    sql = AgentWorkflowService._build_simple_table_sql("订单表有多少条", "giikin.ods_order")
    assert "COUNT(*)" in sql
    assert "giikin.ods_order" in sql


def test_build_simple_table_sql_preview() -> None:
    sql = AgentWorkflowService._build_simple_table_sql("查一下订单表", "giikin.ods_order")
    assert sql.upper().startswith("SELECT * FROM")
    assert "giikin.ods_order" in sql


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_single_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentWorkflowService()

    class _Bff:
        async def search_tables(self, keyword: str):
            assert keyword == "订单"
            return [
                {
                    "project": "giikin",
                    "table_name": "dwd_trade_order_detail",
                    "comment": "订单明细",
                    "entity_guid": "odps.giikin.dwd_trade_order_detail",
                }
            ]

        async def get_upstream_tasks(self, guid: str):
            return [{"id": 1}, {"id": 2}]

        async def list_meta_albums(self, page_size: int = 100):
            return []

        async def get_meta_album(self, album_id: int):
            return None

    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", _Bff())
    plan = await service._resolve_table_via_bff_search("订单", "查一下订单表")
    assert plan is not None
    assert plan.table == "giikin.dwd_trade_order_detail"
    assert "dwd_trade_order_detail" in plan.sql


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_multiple_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentWorkflowService()

    class _Bff:
        async def search_tables(self, keyword: str):
            return [
                {
                    "project": "giikin",
                    "table_name": "ods_order",
                    "comment": "订单贴源",
                    "entity_guid": "odps.giikin.ods_order",
                },
                {
                    "project": "giikin",
                    "table_name": "dwd_trade_order_detail",
                    "comment": "订单明细",
                    "entity_guid": "odps.giikin.dwd_trade_order_detail",
                },
            ]

        async def get_upstream_tasks(self, guid: str):
            return []

        async def list_meta_albums(self, page_size: int = 100):
            return []

        async def get_meta_album(self, album_id: int):
            return None

    # Default behaviour now excludes the ODS candidate ("ods_*" / "tb_ods_*"),
    # leaving only the single DWD candidate — which resolves to a single-hit
    # plan instead of a clarification list.
    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", _Bff())
    plan = await service._resolve_table_via_bff_search("订单", "查一下订单表")
    assert plan is not None
    assert plan.table == "giikin.dwd_trade_order_detail"


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_ods_marker_keeps_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentWorkflowService()

    class _Bff:
        async def search_tables(self, keyword: str):
            return [
                {
                    "project": "giikin",
                    "table_name": "ods_order",
                    "comment": "订单贴源",
                    "entity_guid": "odps.giikin.ods_order",
                },
                {
                    "project": "giikin",
                    "table_name": "dwd_trade_order_detail",
                    "comment": "订单明细",
                    "entity_guid": "odps.giikin.dwd_trade_order_detail",
                },
            ]

        async def get_upstream_tasks(self, guid: str):
            return []

        async def list_meta_albums(self, page_size: int = 100):
            return []

        async def get_meta_album(self, album_id: int):
            return None

    from dataworks_agent.agent.workflow_service import QueryNeedsClarificationError
    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", _Bff())
    with pytest.raises(QueryNeedsClarificationError) as exc:
        await service._resolve_table_via_bff_search("订单", "查订单 ods 表")
    assert len(exc.value.knowledge_matches) == 2

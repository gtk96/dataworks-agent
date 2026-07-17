"""Unit tests for native Chinese table lookup helpers (data-mcp style)."""

from __future__ import annotations

import pytest

from dataworks_agent.agent.workflow_service import AgentWorkflowService


@pytest.fixture(autouse=True)
def _reset_app_state_bff():
    """Ensure app_state._bff_client is freshly populated per test."""
    from dataworks_agent.state import app_state

    prev = getattr(app_state, "_bff_client", None)
    yield
    if prev is not None:
        app_state._bff_client = prev


@pytest.fixture(autouse=True)
def _reset_album_keyword_cache():
    """Reset the per-keyword album cache between tests so previous test
    results don't leak in via the keyword cache."""
    from dataworks_agent.state import app_state

    prev_cache = getattr(app_state, "_album_keyword_cache", None)
    app_state._album_keyword_cache = {}
    yield
    app_state._album_keyword_cache = prev_cache


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


def test_table_layer_extraction() -> None:
    assert AgentWorkflowService._table_layer("ods_order") == "ods"
    assert AgentWorkflowService._table_layer("dwd_trade_order_detail") == "dwd"
    assert AgentWorkflowService._table_layer("giikin_aliyun.tb_dwd_ord_x") == "dwd"
    assert AgentWorkflowService._table_layer("dws_sales_daily") == "dws"
    assert AgentWorkflowService._table_layer("unknown_table") == ""


def test_extract_layer_filter() -> None:
    assert AgentWorkflowService._extract_layer_filter("只要 dwd") == "dwd"
    assert AgentWorkflowService._extract_layer_filter("看 dws 的") == "dws"
    assert AgentWorkflowService._extract_layer_filter("随便看看") == ""


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
    """Single BFF candidate with no album evidence → single-hit plan."""
    service = AgentWorkflowService()
    provider = service._metadata_provider

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
            raise RuntimeError("album metadata unavailable")

        async def get_meta_album(self, album_id: int):
            return None

    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", _Bff())
    result = await provider.search_table("订单", "查一下订单表")
    assert result is not None
    plan = await service._build_plan_from_metadata("查一下订单表", "订单", result)
    assert plan is not None
    assert plan.table == "giikin.dwd_trade_order_detail"
    assert "dwd_trade_order_detail" in plan.sql


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_multiple_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No album + multiple BFF candidates → defer to semantic layer (None)."""
    service = AgentWorkflowService()
    provider = service._metadata_provider

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
            raise RuntimeError("album metadata unavailable")

        async def get_meta_album(self, album_id: int):
            return None

    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", _Bff())
    result = await provider.search_table("订单", "查一下订单表")
    assert result is None  # defers to semantic layer (no album + multi)


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_album_hit_keeps_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an album is known, the resolver keeps both candidates and
    raises a clarification error so the user can pick the right one."""
    service = AgentWorkflowService()

    async def fake_entities(album_id: int, page_size: int = 500):
        return [
            {
                "project": "giikin",
                "table_name": "dwd_trade_order_detail",
                "comment": "订单明细",
                "entity_guid": "odps.giikin.dwd_trade_order_detail",
            },
            {
                "project": "giikin",
                "table_name": "dws_sales_order_daily",
                "comment": "订单汇总",
                "entity_guid": "odps.giikin.dws_sales_order_daily",
            },
            {
                "project": "giikin_aliyun",
                "table_name": "tb_dws_ord_third_daily",
                "comment": "三方订单日报",
                "entity_guid": "odps.giikin_aliyun.tb_dws_ord_third_daily",
            },
        ]

    class _Bff:
        async def search_tables(self, keyword: str):
            return [
                {
                    "project": "giikin",
                    "table_name": "dwd_trade_order_detail",
                    "comment": "订单明细",
                    "entity_guid": "odps.giikin.dwd_trade_order_detail",
                },
                {
                    "project": "giikin",
                    "table_name": "dws_sales_order_daily",
                    "comment": "订单汇总",
                    "entity_guid": "odps.giikin.dws_sales_order_daily",
                },
            ]

        async def get_upstream_tasks(self, guid: str):
            return []

        async def list_meta_albums(self, page_size: int = 100):
            # Returning a non-empty album list so the fallback scoring
            # in ``_resolve_keyword_album`` can pick a match. Returning
            # [] would short-circuit to ``None`` and skip the album path
            # entirely.
            return [
                {
                    "id": 1,
                    "albumName": "订单业务域",
                    "albumDesc": "订单相关业务表",
                }
            ]

        async def get_meta_album(self, album_id: int):
            return {
                "albumId": album_id,
                "albumName": "订单业务域",
                "albumDesc": "订单相关业务表",
            }

    async def fake_album(keyword: str):
        return {
            "album_id": 1,
            "name": "订单业务域",
            "description": "订单相关业务表",
            "score": 10.0,
        }

    service._resolve_keyword_album = fake_album

    from dataworks_agent.agent.workflow_service import QueryNeedsClarificationError
    from dataworks_agent.state import app_state

    bff = _Bff()
    bff.list_meta_album_entities = fake_entities
    monkeypatch.setattr(app_state, "_bff_client", bff)

    with pytest.raises(QueryNeedsClarificationError) as exc:
        await service._resolve_table_via_bff_search("订单", "查一下订单表")
    assert len(exc.value.knowledge_matches) >= 2


@pytest.mark.asyncio
async def test_resolve_table_via_bff_search_ods_marker_keeps_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ODS marker + album known keeps both ODS and DWD candidates so the
    user can pick the right layer."""
    service = AgentWorkflowService()

    async def fake_entities(album_id: int, page_size: int = 500):
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
                {
                    "project": "giikin",
                    "table_name": "dws_sales_order_daily",
                    "comment": "订单汇总",
                    "entity_guid": "odps.giikin.dws_sales_order_daily",
                },
            ]

        async def get_upstream_tasks(self, guid: str):
            return []

        async def list_meta_albums(self, page_size: int = 100):
            return [
                {
                    "id": 1,
                    "albumName": "订单业务域",
                    "albumDesc": "订单相关业务表",
                }
            ]

        async def get_meta_album(self, album_id: int):
            return {
                "albumId": album_id,
                "albumName": "订单业务域",
                "albumDesc": "订单相关业务表",
            }

    async def fake_album(keyword: str):
        return {
            "album_id": 1,
            "name": "订单业务域",
            "description": "订单相关业务表",
            "score": 10.0,
        }

    service._resolve_keyword_album = fake_album

    bff = _Bff()
    bff.list_meta_album_entities = fake_entities
    from dataworks_agent.state import app_state

    monkeypatch.setattr(app_state, "_bff_client", bff)

    # ``查订单 ods 表`` triggers the layer filter (``ods``), which narrows
    # the album candidates to a single ODS row -> single-hit plan rather
    # than a clarification list.
    plan = await service._resolve_table_via_bff_search("订单", "查订单 ods 表")
    assert plan is not None
    assert plan.table == "giikin.ods_order"

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from dataworks_agent.semantic.album_context import DataAlbumContextResolver


class FakeAlbumClient:
    def __init__(self) -> None:
        self.list_meta_albums = AsyncMock(
            return_value=[
                {
                    "id": 505,
                    "albumName": "\u91d1\u72ee\u5bb6\u65cf",
                    "albumDesc": "\u5bb6\u65cf\u4e1a\u52a1\u6a21\u578b",
                },
                {"id": 888, "albumName": "\u8ba2\u5355", "albumDesc": "\u8ba2\u5355\u4e3b\u9898"},
                {
                    "id": 409,
                    "albumName": "\u5e7f\u544a\u62a5\u8868",
                    "albumDesc": "\u5e7f\u544a\u6d41\u8f6c",
                },
            ]
        )
        self.get_meta_album = AsyncMock(
            return_value={"id": 888, "albumName": "订单", "albumDesc": "订单主题"}
        )
        self.list_meta_album_categories = AsyncMock(
            return_value=[{"id": 1, "categoryName": "\u8ba2\u5355\u4fe1\u606f"}]
        )
        self.list_meta_album_entities = AsyncMock(side_effect=self._entities)

    @staticmethod
    async def _entities(album_id: int, **_: object) -> list[dict]:
        if album_id == 505:
            return [
                {
                    "project": "giikin_aliyun",
                    "table_name": "vw_dws_ord_order_si_js_di",
                    "comment": "\u91d1\u72ee\u5bb6\u65cf\u8ba2\u5355\u6c47\u603b",
                    "remark": "",
                    "category_id": 1,
                    "entity_type": "odps-table",
                }
            ]
        return [
            {
                "project": "giikin_aliyun",
                "table_name": "tb_ods_ord_order_di",
                "comment": "\u8ba2\u5355\u660e\u7ec6",
                "remark": "",
                "category_id": 1,
                "entity_type": "odps-table",
            },
            {
                "project": "giikin_aliyun",
                "table_name": "tb_dws_ord_order_si_crt_df",
                "comment": "\u8ba2\u5355\u6307\u6807\u6c47\u603b",
                "remark": "\u6309\u8ba2\u5355\u65e5\u671f\u5206\u533a",
                "category_id": 1,
                "entity_type": "odps-table",
            },
        ]


@pytest.mark.asyncio
async def test_family_order_question_matches_family_and_order_albums():
    resolver = DataAlbumContextResolver(FakeAlbumClient())

    contexts = await resolver.resolve(
        "\u67e5\u4e00\u4e0b\u4eca\u5929\u5404\u5bb6\u65cf\u7684\u6709\u6548\u8ba2\u5355\u6570"
    )

    names = [context.name for context in contexts]
    assert "\u91d1\u72ee\u5bb6\u65cf" in names
    assert "\u8ba2\u5355" in names
    assert "\u5e7f\u544a\u62a5\u8868" not in names


@pytest.mark.asyncio
async def test_dws_candidate_ranks_above_ods_for_order_question():
    resolver = DataAlbumContextResolver(FakeAlbumClient())

    contexts = await resolver.resolve("\u8ba2\u5355\u6570\u662f\u591a\u5c11")
    order_context = next(context for context in contexts if context.name == "\u8ba2\u5355")

    assert order_context.tables[0].name == "tb_dws_ord_order_si_crt_df"
    assert order_context.tables[1].name == "tb_ods_ord_order_di"


@pytest.mark.asyncio
async def test_manual_remark_has_stronger_ranking_weight():
    client = FakeAlbumClient()
    client.list_meta_albums = AsyncMock(
        return_value=[{"id": 1, "albumName": "\u8ba2\u5355", "albumDesc": ""}]
    )
    client.list_meta_album_entities = AsyncMock(
        return_value=[
            {
                "project": "p",
                "table_name": "tb_dws_ord_summary",
                "comment": "",
                "remark": "",
                "entity_type": "odps-table",
            },
            {
                "project": "p",
                "table_name": "tb_dwd_ord_detail",
                "comment": "",
                "remark": "\u6709\u6548\u8ba2\u5355\u4e13\u7528\u53e3\u5f84",
                "entity_type": "odps-table",
            },
        ]
    )
    resolver = DataAlbumContextResolver(client)

    contexts = await resolver.resolve("\u6709\u6548\u8ba2\u5355")

    assert contexts[0].tables[0].name == "tb_dwd_ord_detail"


@pytest.mark.asyncio
async def test_album_failure_returns_empty_context_without_raising():
    client = FakeAlbumClient()
    client.list_meta_albums = AsyncMock(side_effect=RuntimeError("cookie expired"))
    resolver = DataAlbumContextResolver(client)

    assert await resolver.resolve("\u8ba2\u5355\u6570") == []


@pytest.mark.asyncio
async def test_unmatched_question_does_not_invent_album():
    resolver = DataAlbumContextResolver(FakeAlbumClient())

    assert await resolver.resolve("\u5458\u5de5\u98df\u5802\u83dc\u8c31") == []


@pytest.mark.asyncio
async def test_required_certified_table_is_kept_beyond_normal_candidate_limit():
    client = FakeAlbumClient()
    client.list_meta_albums = AsyncMock(
        return_value=[{"id": 888, "albumName": "订单", "albumDesc": "订单主题"}]
    )
    client.list_meta_album_entities = AsyncMock(
        return_value=[
            {
                "project": "giikin_aliyun",
                "table_name": "tb_rp_other_order_metric",
                "comment": "订单指标汇总",
                "entity_type": "odps-table",
            },
            {
                "project": "giikin_aliyun",
                "table_name": "tb_dws_ord_order_si_crt_df",
                "comment": "小时预警",
                "entity_type": "odps-table",
            },
        ]
    )
    resolver = DataAlbumContextResolver(client)

    contexts = await resolver.resolve(
        "今天有效订单是多少",
        max_tables=1,
        required_tables={"giikin_aliyun.tb_dws_ord_order_si_crt_df"},
    )

    names = {table.full_name for table in contexts[0].tables}
    assert "giikin_aliyun.tb_dws_ord_order_si_crt_df" in names


@pytest.mark.asyncio
async def test_required_album_is_loaded_when_album_listing_is_empty():
    client = FakeAlbumClient()
    client.list_meta_albums = AsyncMock(return_value=[])
    resolver = DataAlbumContextResolver(client)

    contexts = await resolver.resolve(
        "今天有效订单是多少",
        required_tables={"giikin_aliyun.tb_dws_ord_order_si_crt_df"},
        required_album_ids={888},
    )

    assert [context.album_id for context in contexts] == [888]
    assert contexts[0].name == "订单"
    assert any(
        table.full_name == "giikin_aliyun.tb_dws_ord_order_si_crt_df"
        for table in contexts[0].tables
    )
    client.get_meta_album.assert_awaited_once_with(888)

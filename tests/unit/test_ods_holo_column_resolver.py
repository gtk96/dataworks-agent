"""Unit tests for Holo ODS column resolver."""

from __future__ import annotations

import pytest

from dataworks_agent.services.ods_holo.column_resolver import (
    _append_ods_partition_columns,
    load_holo_ods_columns,
)


class TestAppendOdsPartitionColumns:
    def test_hour_adds_update_ht_dt_ht(self) -> None:
        names = _append_ods_partition_columns(["order_id"], "hour")
        assert names == ["order_id", "update_ht", "dt", "ht"]

    def test_day_adds_dt_only(self) -> None:
        names = _append_ods_partition_columns(["order_id"], "day")
        assert names == ["order_id", "dt"]


class TestLoadHoloOdsColumns:
    @pytest.mark.asyncio
    async def test_prefers_snapshot_over_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _snapshot(*_args: object, **_kwargs: object) -> list[dict]:
            return [{"column_name": "id", "data_type": "bigint", "column_key": "PRI"}]

        async def _registry(*_args: object, **_kwargs: object) -> list[dict] | None:
            return [{"column_name": "id", "data_type": "bigint", "column_key": ""}]

        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.column_resolver.query_columns",
            _snapshot,
        )
        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.column_resolver.query_columns_from_ddl_registry",
            _registry,
        )

        resolved = await load_holo_ods_columns(object(), object(), "ofc", "s_order", "hour")
        assert resolved["status"] == "ok"
        assert resolved["metadata_source"] == "snapshot"
        assert resolved["source_columns"][0]["column_key"] == "PRI"
        assert "update_ht" in resolved["target_columns"]

    @pytest.mark.asyncio
    async def test_failed_when_no_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _empty(*_args: object, **_kwargs: object):
            return None

        async def _infer_failed(*_args: object, **_kwargs: object) -> dict:
            return {"status": "failed", "error": "x"}

        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.column_resolver.query_columns",
            _empty,
        )
        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.column_resolver.query_columns_from_ddl_registry",
            _empty,
        )
        monkeypatch.setattr(
            "dataworks_agent.services.ods_holo.column_resolver.infer_fields",
            _infer_failed,
        )

        resolved = await load_holo_ods_columns(object(), object(), "ofc", "missing", "hour")
        assert resolved["status"] == "failed"
        assert resolved["column_count"] == 0

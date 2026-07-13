"""word_root_sync 单元测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dataworks_agent.db.database import Base
from dataworks_agent.governance import word_root_sync as mod
from dataworks_agent.governance.word_root_sync import _parse_root_rows, get_word_root_sync_meta
from dataworks_agent.standards.loader import clear_word_root_loader_cache, load_word_root_entries


@pytest.fixture
def word_root_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr("dataworks_agent.db.database.SessionLocal", session_factory)
    monkeypatch.setattr(mod, "SessionLocal", session_factory)
    clear_word_root_loader_cache()
    yield
    clear_word_root_loader_cache()
    engine.dispose()


def test_parse_root_rows_skips_header() -> None:
    rows = [
        ["column_name", "column_desc", "is_digit"],
        ["order_id", "订单ID", "0"],
        ["order_amt", "订单金额", "1"],
    ]
    entries = _parse_root_rows(rows)
    assert len(entries) == 2
    assert entries[0]["column_name"] == "order_id"
    assert entries[1]["is_digit"] is True


def test_parse_root_rows_deduplicates_column_names() -> None:
    rows = [
        ["column_name", "column_desc", "is_digit"],
        ["order_id", "", "0"],
        ["order_id", "Order ID", "0"],
        ["order_amt", "Order amount", "1"],
    ]

    entries = _parse_root_rows(rows)

    assert entries == [
        {"column_name": "order_id", "column_desc": "Order ID", "is_digit": False},
        {"column_name": "order_amt", "column_desc": "Order amount", "is_digit": True},
    ]


def test_persist_and_load_from_db(word_root_db) -> None:
    mod._persist_entries(
        [
            {"column_name": "order_id", "column_desc": "订单ID", "is_digit": False},
            {"column_name": "order_amt", "column_desc": "订单金额", "is_digit": True},
        ],
        "2026-07-09T00:00:00Z",
    )
    clear_word_root_loader_cache()
    entries = load_word_root_entries()
    assert len(entries) == 2
    meta = get_word_root_sync_meta()
    assert meta["source"] == "online"
    assert meta["total"] == 2
    assert meta["synced_at"] == "2026-07-09T00:00:00Z"


@pytest.mark.asyncio
async def test_sync_word_roots_from_online(monkeypatch, word_root_db) -> None:
    async def _run(*args, **kwargs):
        return [
            ["order_id", "订单ID", "0"],
            ["badtoken", "非法", "0"],
        ]

    monkeypatch.setattr(
        "dataworks_agent.services.ods_di.sql_runner.run_odps_query",
        _run,
    )

    result = await mod.sync_word_roots_from_online()
    assert result["status"] == "ok"
    assert result["count"] == 2
    clear_word_root_loader_cache()
    assert len(load_word_root_entries()) == 2

"""LineageStore 持久化缓存 — 单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select

from dataworks_agent.db.database import Base
from dataworks_agent.db.models import LineageEdgeModel
from dataworks_agent.governance import lineage_store as store_mod
from dataworks_agent.governance.lineage_store import LineageStore


@pytest.fixture
def store(tmp_path) -> tuple[LineageStore, Any]:
    """用临时 SQLite 替代业务 DB,跑 LineageStore。"""
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.orm import sessionmaker

    db_file = tmp_path / "lineage_test.db"
    test_engine = sa_create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, autoflush=False)

    with patch.object(store_mod, "SessionLocal", test_session):
        s = LineageStore()
        yield s, test_session


def test_save_and_get_upstream(store):
    s, _ = store
    s.save_edges("ods_a", "dwd_b", task_id="1001", task_name="task_a_to_b")
    rows = s.get_upstream("dwd_b")
    assert len(rows) == 1
    assert rows[0]["source_table"] == "ods_a"
    assert rows[0]["target_table"] == "dwd_b"
    assert rows[0]["task_id"] == "1001"
    assert rows[0]["task_name"] == "task_a_to_b"


def test_save_strips_schema_prefix(store):
    """odps.project.table 形式自动去 schema。"""
    s, _ = store
    s.save_edges("odps.dataworks.ods_a", "odps.dataworks.dwd_b")
    rows = s.get_upstream("dwd_b")
    assert rows[0]["source_table"] == "ods_a"
    assert rows[0]["target_table"] == "dwd_b"


def test_save_self_loop_ignored(store):
    """source == target 不写。"""
    s, _ = store
    s.save_edges("t1", "t1")
    assert s.get_upstream("t1") == []
    assert s.get_downstream("t1") == []


def test_save_empty_strings_ignored(store):
    s, _ = store
    s.save_edges("", "dwd_b")
    s.save_edges("ods_a", "")
    assert s.get_upstream("dwd_b") == []


def test_duplicate_edge_updates_cached_at(store):
    """同 (source, target) 二次写只更新 cached_at,不产生新行。"""
    s, _ = store
    s.save_edges("ods_a", "dwd_b", task_id="v1")
    first = s.get_upstream("dwd_b")[0]
    first_cached = first["cached_at"]

    import time

    time.sleep(1.1)
    s.save_edges("ods_a", "dwd_b", task_id="v2", task_name="updated")
    rows = s.get_upstream("dwd_b")
    assert len(rows) == 1, "应只 1 条记录,不是 2 条"
    assert rows[0]["task_id"] == "v2"
    assert rows[0]["task_name"] == "updated"
    assert rows[0]["cached_at"] > first_cached


def test_get_downstream(store):
    s, _ = store
    s.save_edges("ods_a", "dwd_b")
    s.save_edges("ods_a", "dwd_c")
    s.save_edges("ods_x", "dwd_b")  # 不应被下游查返回
    rows = s.get_downstream("ods_a")
    assert len(rows) == 2
    targets = {r["target_table"] for r in rows}
    assert targets == {"dwd_b", "dwd_c"}


def test_is_fresh_true_for_recently_cached(store):
    s, _ = store
    s.save_edges("ods_a", "dwd_b")
    assert s.is_fresh("dwd_b") is True
    assert s.is_fresh("ods_a") is True  # 边一端在 TTL 内即视为 fresh


def test_is_fresh_false_for_unknown_table(store):
    s, _ = store
    assert s.is_fresh("nonexistent_table") is False


def test_is_fresh_false_after_ttl(store):
    """自定义 TTL 1s,等 1.1s 后应过期。"""
    s, _ = store
    s.ttl = timedelta(seconds=1)
    s.save_edges("ods_a", "dwd_b")

    # 内部 cached_at 是写入瞬间,is_fresh 比较 timedelta(1s)
    assert s.is_fresh("dwd_b") is True
    # 把 cached_at 改到 2 秒前
    with store_mod.SessionLocal() as db:
        row = db.execute(select(LineageEdgeModel).limit(1)).scalar_one()
        row.cached_at = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
        db.commit()
    assert s.is_fresh("dwd_b") is False


def test_clear_removes_all_edges_for_table(store):
    s, _ = store
    s.save_edges("ods_a", "dwd_b")
    s.save_edges("dwd_b", "dws_c")
    s.save_edges("ods_x", "dwd_y")  # 无关边

    deleted = s.clear("dwd_b")
    assert deleted == 2
    assert s.get_upstream("dwd_b") == []
    assert s.get_downstream("dwd_b") == []
    # 无关边保留
    assert s.get_downstream("ods_x") != []


def test_save_edges_batch(store):
    s, _ = store
    n = s.save_edges_batch(
        [
            {"source_table": "ods_a", "target_table": "dwd_b"},
            {"source_table": "ods_b", "target_table": "dwd_b"},
            {"source_table": "ods_c", "target_table": "dwd_b"},
        ]
    )
    assert n == 3
    rows = s.get_upstream("dwd_b")
    assert len(rows) == 3


def test_get_upstream_skips_expired(store):
    """过期边不应返回。"""
    s, _ = store
    s.ttl = timedelta(seconds=1)
    s.save_edges("ods_a", "dwd_b")
    with store_mod.SessionLocal() as db:
        row = db.execute(select(LineageEdgeModel).limit(1)).scalar_one()
        row.cached_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        db.commit()
    assert s.get_upstream("dwd_b") == []

"""_ensure_columns 自愈迁移单测（Task 7 迁移点固化）。

模拟历史库：手建一个缺 Task 7 新列的旧版 modeling_tasks 表，调用后确认缺列被补齐，
且幂等（二次调用不报错）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect

import dataworks_agent.db.models  # noqa: F401 — 触发模型注册
from dataworks_agent.db.database import _ensure_columns


def _cols(eng, table):
    return {c["name"] for c in inspect(eng).get_columns(table)}


def test_adds_missing_columns_to_existing_table(tmp_path):
    db = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db}")
    # 旧版表：只有主键与 status，缺 Task 7 的 actor_team/actor_org_code 等
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE modeling_tasks (task_id TEXT PRIMARY KEY, status TEXT)")

    _ensure_columns(eng)

    cols = _cols(eng, "modeling_tasks")
    assert "actor_team" in cols
    assert "actor_org_code" in cols
    # 既有列不动
    assert "task_id" in cols and "status" in cols


def test_idempotent(tmp_path):
    db = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE modeling_tasks (task_id TEXT PRIMARY KEY, status TEXT)")
    _ensure_columns(eng)
    before = _cols(eng, "modeling_tasks")
    # 二次调用不应报错，也不改变列集合
    _ensure_columns(eng)
    assert _cols(eng, "modeling_tasks") == before


def test_skips_tables_not_present(tmp_path):
    # 空库：无任何表，_ensure_columns 应安全跳过（新表交给 create_all）
    db = tmp_path / "empty.db"
    eng = create_engine(f"sqlite:///{db}")
    _ensure_columns(eng)  # 不抛异常即通过
    assert inspect(eng).get_table_names() == []

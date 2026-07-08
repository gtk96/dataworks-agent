"""SQLite 备份 — 单元测试。

不依赖真实业务数据库,通过 patch 模块级 settings 引用 + 拦截 sqlite3.connect。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dataworks_agent.db import backup as backup_mod
from dataworks_agent.db.backup import (
    backup_db,
    incremental_backup_on_event,
)


def test_backup_db_creates_consistent_copy(tmp_path: Path):
    """backup_db 写 .bak 文件,内容跟源库一致。"""
    src_path = str(tmp_path / "src.db")
    conn = sqlite3.connect(src_path)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    conn.commit()
    conn.close()

    fake_settings = SimpleNamespace(db_path=src_path)
    with patch.object(backup_mod, "settings", fake_settings):
        backup_db()

    bak = src_path + ".bak"
    assert Path(bak).exists()
    out = sqlite3.connect(bak)
    rows = out.execute("SELECT id, name FROM t ORDER BY id").fetchall()
    out.close()
    assert rows == [(1, "a"), (2, "b"), (3, "c")]


def test_backup_db_overwrites_previous(tmp_path: Path):
    """第二次 backup 覆盖 .bak,内容更新。"""
    src_path = str(tmp_path / "src.db")
    conn = sqlite3.connect(src_path)
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    fake_settings = SimpleNamespace(db_path=src_path)
    with patch.object(backup_mod, "settings", fake_settings):
        backup_db()
        first_bak_mtime = Path(src_path + ".bak").stat().st_mtime

        # 改源库
        conn = sqlite3.connect(src_path)
        conn.execute("DELETE FROM t")
        conn.execute("INSERT INTO t VALUES (99)")
        conn.commit()
        conn.close()

        import time

        time.sleep(1.1)  # 跨秒

        backup_db()
        second_bak_mtime = Path(src_path + ".bak").stat().st_mtime

    assert second_bak_mtime > first_bak_mtime
    out = sqlite3.connect(src_path + ".bak")
    assert out.execute("SELECT v FROM t").fetchall() == [(99,)]
    out.close()


@pytest.mark.asyncio
async def test_incremental_backup_triggered_events(monkeypatch):
    """关键事件触发备份,非关键事件不触发。"""
    backup_calls: list[str] = []

    def fake_backup() -> None:
        backup_calls.append("called")

    monkeypatch.setattr(backup_mod, "backup_db", fake_backup)

    for event in ("TaskCompleted", "TaskFailed", "TableCreated"):
        await incremental_backup_on_event(event, "task-1")
        assert len(backup_calls) == 1, f"{event} 应该触发备份"
        backup_calls.clear()

    for event in ("TaskCreated", "RandomEvent", ""):
        await incremental_backup_on_event(event, "task-1")
        assert backup_calls == [], f"{event} 不应该触发备份"


@pytest.mark.asyncio
async def test_incremental_backup_swallows_errors(monkeypatch):
    """backup 失败不应该让 incremental_backup_on_event 抛异常。"""

    def bad_backup() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(backup_mod, "backup_db", bad_backup)
    await incremental_backup_on_event("TaskCompleted", "task-1")

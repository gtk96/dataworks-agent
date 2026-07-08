"""SQLite 热备份 — 使用 SQLite Backup API 保证事务一致性。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)


def backup_db() -> None:
    """使用 SQLite Backup API 创建事务一致性快照。"""
    src = sqlite3.connect(settings.db_path)
    dst_path = f"{settings.db_path}.bak"
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


async def scheduled_backup() -> None:
    """每小时执行一次全量备份。"""
    while True:
        await asyncio.sleep(3600)
        try:
            backup_db()
            logger.info("数据库备份完成")
        except Exception as e:
            logger.exception("数据库备份失败: %s", e)


async def incremental_backup_on_event(event: str, task_id: str) -> None:
    """在任务关键事件（完成/失败/建表）后触发增量备份，降低 RPO。"""
    triggered_events = {"TaskCompleted", "TaskFailed", "TableCreated"}
    if event in triggered_events:
        with contextlib.suppress(Exception):
            backup_db()

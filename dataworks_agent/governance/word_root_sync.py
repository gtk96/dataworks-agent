"""从线上词根表同步到本地 SQLite 缓存。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select

from dataworks_agent.config import settings
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import WordRootCacheModel

logger = logging.getLogger(__name__)

WORD_ROOT_TABLE = "dim_pub_column_dictionary_static"

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_root_rows(body_list: list[list[Any]]) -> list[dict[str, Any]]:
    """解析 ODPS 查询结果行。"""
    if not body_list:
        return []

    entries: list[dict[str, Any]] = []
    start_idx = 0
    first = [str(cell or "").strip().lower() for cell in body_list[0]]
    if first and first[0] in {"column_name", "字段名"}:
        start_idx = 1

    for row in body_list[start_idx:]:
        if not row:
            continue
        name = str(row[0] or "").strip()
        if not name:
            continue
        desc = str(row[1] or "").strip() if len(row) > 1 else ""
        digit_raw = row[2] if len(row) > 2 else 0
        is_digit = str(digit_raw).strip().lower() in {"1", "true", "yes"}
        entries.append(
            {
                "column_name": name,
                "column_desc": desc,
                "is_digit": is_digit,
            }
        )
    return entries


def _persist_entries(entries: list[dict[str, Any]], refreshed_at: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(WordRootCacheModel))
        db.bulk_save_objects(
            [
                WordRootCacheModel(
                    column_name=item["column_name"],
                    column_desc=item.get("column_desc", ""),
                    is_digit=1 if item.get("is_digit") else 0,
                    refreshed_at=refreshed_at,
                )
                for item in entries
            ]
        )
        db.commit()


def clear_word_root_caches() -> None:
    """清空 loader LRU 与 API 内存缓存。"""
    from dataworks_agent.cache import get_cache_manager
    from dataworks_agent.standards.loader import clear_word_root_loader_cache

    clear_word_root_loader_cache()
    get_cache_manager().invalidate_by_source("word_roots")


def get_word_root_sync_meta() -> dict[str, Any]:
    """读取本地词根缓存元信息。"""
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(WordRootCacheModel)) or 0
        synced_at = db.scalar(select(func.max(WordRootCacheModel.refreshed_at))) or ""
    if total:
        schema = settings.dataworks_prod_schema or settings.maxcompute_project or "dataworks"
        return {
            "source": "online",
            "total": int(total),
            "synced_at": synced_at,
            "table": f"{schema}.{WORD_ROOT_TABLE}",
        }
    return {"source": "bundled", "total": 0, "synced_at": "", "table": ""}


async def sync_word_roots_from_online() -> dict[str, Any]:
    """从 MaxCompute 词根表拉取最新数据并写入本地缓存。"""
    from dataworks_agent.services.ods_di.sql_runner import run_odps_query
    from dataworks_agent.state import app_state

    schema = settings.dataworks_prod_schema or settings.maxcompute_project or "dataworks"
    sql = f"""
select column_name, column_desc, is_digit
from {schema}.{WORD_ROOT_TABLE}
where column_name is not null and trim(column_name) <> ''
""".strip()

    bff = getattr(app_state, "_bff_client", None)
    mcp = app_state.mcp_pool
    rows = await run_odps_query(bff, mcp, sql)
    if not rows:
        raise RuntimeError(
            "无法从线上词根表拉取数据（MaxCompute/BFF/MCP 不可用或查询失败）"
        )

    entries = _parse_root_rows(rows)
    if not entries:
        raise RuntimeError("线上词根表返回空结果，请检查表权限或 SQL")

    refreshed_at = _utc_now()
    _persist_entries(entries, refreshed_at)
    clear_word_root_caches()
    logger.info("词根同步完成: %d 条, table=%s.%s", len(entries), schema, WORD_ROOT_TABLE)

    return {
        "status": "ok",
        "count": len(entries),
        "refreshed_at": refreshed_at,
        "source": "online",
        "table": f"{schema}.{WORD_ROOT_TABLE}",
    }


def touch_word_root_sync(**fields: Any) -> None:
    """更新词根自动同步状态（供 API / 运维查看）。"""
    from dataworks_agent.state import app_state

    state = dict(getattr(app_state, "word_root_sync", {}) or {})
    state.update(fields)
    state["updated_at"] = _utc_now()
    app_state.word_root_sync = state


def _format_interval(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours and not mins:
        return f"每 {hours} 小时"
    if hours:
        return f"每 {hours} 小时 {mins} 分钟"
    return f"每 {max(mins, 1)} 分钟"


async def run_word_root_sync_once(*, force: bool = False) -> dict[str, Any]:
    """执行一次词根同步（定时/启动用；force=True 时忽略 auto_sync 开关）。"""
    if not force and not settings.word_root_auto_sync_enabled:
        touch_word_root_sync(action="disabled", detail="WORD_ROOT_AUTO_SYNC_ENABLED=false")
        return {"status": "skipped", "detail": "auto sync disabled"}

    try:
        result = await sync_word_roots_from_online()
        touch_word_root_sync(
            action="success",
            detail=f"{result['count']} 条",
            last_sync_at=result["refreshed_at"],
            last_count=result["count"],
            last_error="",
        )
        return result
    except Exception as exc:
        logger.warning("词根同步失败: %s", exc)
        touch_word_root_sync(action="error", detail=str(exc)[:200], last_error=str(exc)[:200])
        return {"status": "failed", "detail": str(exc)}


async def word_root_sync_loop(stop: asyncio.Event) -> None:
    """后台定时从生产词根表同步到本地。"""
    logger.info("词根自动同步任务已启动")
    try:
        while not stop.is_set():
            if not settings.word_root_auto_sync_enabled:
                touch_word_root_sync(action="disabled", detail="WORD_ROOT_AUTO_SYNC_ENABLED=false")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=60.0)
                continue

            interval = max(300, int(settings.word_root_sync_interval_seconds))
            touch_word_root_sync(
                action="scheduled",
                detail=_format_interval(interval),
                interval_seconds=interval,
            )

            await run_word_root_sync_once()

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=float(interval))
    except asyncio.CancelledError:
        logger.info("词根自动同步任务已停止")
        raise


def get_word_root_sync_status() -> dict[str, Any]:
    """词根自动同步状态 + 本地缓存元信息。"""
    from dataworks_agent.state import app_state

    meta = get_word_root_sync_meta()
    poll = dict(getattr(app_state, "word_root_sync", {}) or {})
    return {
        "auto_sync_enabled": bool(settings.word_root_auto_sync_enabled),
        "interval_seconds": settings.word_root_sync_interval_seconds,
        "interval_label": _format_interval(max(300, int(settings.word_root_sync_interval_seconds))),
        "table": meta.get("table") or f"{settings.dataworks_prod_schema}.{WORD_ROOT_TABLE}",
        **meta,
        **poll,
    }

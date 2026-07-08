"""监控 & 仪表盘 API — 统计、趋势、WebSocket 实时推送。

WS 通道语义（v10 重构）：
- 订阅 EventBus.TASK_STATUS_CHANGED，状态变更时主动 fanout 给所有连接
- 客户端仅需发任意文本（保活），**不需要**触发服务端 SQL 查询
- 客户端断连 / 死连接自动清理（send 失败即踢出）
"""

from __future__ import annotations

import json
import logging
from datetime import UTC

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dataworks_agent.cache.events import Event, EventType, get_event_bus
from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel

logger = logging.getLogger(__name__)

router = APIRouter()

# WebSocket 连接池 — 用 set 而非 list，O(1) 移除死连接
_ws_clients: set[WebSocket] = set()


@router.get("/dashboard")
async def dashboard():
    """仪表盘统计: 成功率、平均耗时、24h 趋势、按层分布。

    R18 stale-write 修复：cache 读取前先 peek_invalidation_epoch 拿到"开始算时"的 epoch，
    SQL 跑完后用 set(..., min_epoch=epoch) 写入。若 SQL 期间 cache 被 delete 过
    （engine publish TASK_STATUS_CHANGED → _broadcast_task_status → cache.delete），
    set 会返回 False 且不写入，避免把"算到一半时的旧数据"覆盖到 cache。
    """
    from dataworks_agent.cache import get_cache_manager

    cache = get_cache_manager()

    # 先拿 epoch（"开始算时"的失效序号），再做 cache hit 判断
    min_epoch = cache.peek_invalidation_epoch("dashboard")
    cached = cache.get("dashboard")
    if cached is not None:
        return cached

    # 跑 SQL aggregation（耗时操作，可能被 delete 中断）
    result = await _compute_dashboard_stats()

    # 写入 cache，校验 epoch：SQL 期间被 delete 则丢弃 stale write
    cache.set("dashboard", result, ttl=60, min_epoch=min_epoch)
    return result


async def _compute_dashboard_stats() -> dict:
    """仪表盘聚合 SQL — 从 /dashboard 抽出来便于测试 + epoch 校验。"""
    from sqlalchemy import func

    running_statuses = {
        "running",
        "ddl_gen",
        "table_cre",
        "root_check",
        "dml_write",
        "sched_cfg",
        "testing",
    }
    known_layers = ("ODS", "DWD", "DWS", "DMR", "DIM")

    with SessionLocal() as db:
        # R4: 一次 GROUP BY 拿到全部分层状态计数，替代原先约 9 次串行 .count()
        status_rows = (
            db.query(ModelingTaskModel.status, func.count())
            .group_by(ModelingTaskModel.status)
            .all()
        )
        status_counts = {s: c for s, c in status_rows}
        total = sum(status_counts.values())
        completed = status_counts.get("completed", 0)
        failed = status_counts.get("failed", 0)
        pending = status_counts.get("pending", 0)
        running = sum(c for s, c in status_counts.items() if s in running_statuses)

        # 成功率 = 已完成 / (已完成 + 失败), 未完成的(pending/running)不参与计算
        finished = completed + failed
        success_rate = (completed / finished * 100) if finished > 0 else 0

        # 分层计数同样走 GROUP BY（仅纳入已知分层，保持与原逻辑一致）
        layer_rows = (
            db.query(ModelingTaskModel.target_layer, func.count())
            .group_by(ModelingTaskModel.target_layer)
            .all()
        )
        layer_counts = {
            layer: cnt for layer, cnt in layer_rows if layer in known_layers and cnt > 0
        }

        avg_dur = (
            db.query(func.avg(ModelingTaskModel.duration_seconds))
            .filter(ModelingTaskModel.status == "completed")
            .scalar()
            or 0
        )

        # 按节点类型分布（含 pipeline 任务 + 历史推断）
        from dataworks_agent.services.task_classification import aggregate_type_breakdown

        type_breakdown = aggregate_type_breakdown(db)

    # 注：v10 收敛掉 5 个未使用字段（today_completed/today_failed/
    # type_breakdown_labeled/type_labels/queue_backlog）+ 1 个语义
    # 重叠字段（finished = completed + failed，前端按完成/失败分开统计）。
    # active_tasks 与 running 重复也删，running 即活跃任务数。
    return {
        "total_tasks": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "running": running,
        "success_rate": round(success_rate, 1),
        "avg_duration_seconds": round(float(avg_dur), 1),
        "layer_breakdown": layer_counts,
        "type_breakdown": type_breakdown,
    }


# WebSocket 订阅式实时推送（v10 重构）
# 设计：状态机在 transition 处 publish EventBus.TASK_STATUS_CHANGED；
# 这里订阅，事件来了就 fanout 给所有连接。客户端发任意文本仅作 keepalive，
# 服务端不再为此触发 DB 查询。
_event_bus = get_event_bus()


async def _broadcast_task_status(event: Event) -> None:
    """EventBus handler — 任务状态变更时 fanout 到所有 WS 客户端。

    R1 修复：状态一变更就失效 dashboard 聚合缓存，否则 WS 触发的刷新
    会命中 60s 旧缓存、"实时"名存实亡；失效后 WS/轮询都能拿到最新数据。
    v10 §4.2：同步失效 tasks:* 列表缓存（engine 内部 transition 不经过
    modeling._invalidate_tasks_cache 手动调用）。
    """
    from dataworks_agent.cache import get_cache_manager

    cache = get_cache_manager()
    try:
        cache.delete("dashboard")
        cache.invalidate_by_source("tasks")
    except Exception as exc:
        logger.warning(
            "TASK_STATUS_CHANGED 缓存失效失败 task=%s status=%s err=%s",
            event.data.get("task_id") if event.data else None,
            event.data.get("status") if event.data else None,
            exc,
        )
        return

    if not _ws_clients:
        return

    payload = json.dumps(
        {
            "type": "task_status_changed",
            "task_id": event.data.get("task_id") if event.data else None,
            "status": event.data.get("status") if event.data else None,
            "timestamp": event.data.get("timestamp") if event.data else None,
            "request_id": event.data.get("request_id") if event.data else None,
        }
    )

    # 死连接：send_text 会抛；用副本迭代以便踢出
    dead: list[WebSocket] = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception as exc:
            logger.debug("WS send 失败，踢出死连接: %s", exc)
            dead.append(ws)
    if dead:
        logger.debug(
            "WS fanout 踢出 %d/%d 死连接 task=%s",
            len(dead),
            len(_ws_clients) + len(dead),
            event.data.get("task_id") if event.data else None,
        )
    for ws in dead:
        _ws_clients.discard(ws)


# 模块加载时注册订阅（一次性）。R5: dev autoreload / 重复 import 会再次执行本模块，
# 而 EventBus.subscribe 不幂等（每次都 append），会导致重复 fanout。
# 在单例 _event_bus 上打标记，确保进程内只订阅一次。
if not getattr(_event_bus, "_dashboard_ws_subscribed", False):
    _event_bus.subscribe(EventType.TASK_STATUS_CHANGED, _broadcast_task_status)
    _event_bus._dashboard_ws_subscribed = True


@router.websocket("/ws/tasks")
async def ws_tasks(websocket: WebSocket):
    """WebSocket 实时推送任务状态。

    语义：服务端主动推送（事件驱动），客户端发任意文本仅作 keepalive。
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.debug("WS 客户端接入，当前连接数=%d", len(_ws_clients))

    try:
        # 进入后先送一帧 hello，让前端确认通道活着
        await websocket.send_text(json.dumps({"type": "hello", "ts": _now_iso()}))

        while True:
            # 客户端消息仅作 keepalive；不再触发 DB 查询。
            # 业务推送由 _broadcast_task_status 完成。
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WS 异常断开: %s", e)
    finally:
        _ws_clients.discard(websocket)
        logger.debug("WS 客户端断开，当前连接数=%d", len(_ws_clients))


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()

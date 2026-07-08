"""CacheManager epoch-based stale-write 防护 — R18 修复护栏。

覆盖：
1. delete 递增 epoch（peek 能拿到新值）
2. set(min_epoch=) 校验：epoch 已被超过则丢弃
3. set 默认行为（min_epoch=0）向后兼容
4. dashboard endpoint 端到端：stale write 被丢弃

注：CacheManager 是模块级单例，测试间必须用独立 key + 显式清空避免相互污染。
"""

from __future__ import annotations

import uuid

import pytest

from dataworks_agent.cache import get_cache_manager


@pytest.fixture
def cache():
    """每个测试拿到一个 fresh cache — 避免全局单例污染。"""
    cm = get_cache_manager()
    cm.clear()
    # 清空 _epochs dict（不通过公共 API）
    with cm._lock:
        cm._epochs.clear()
    yield cm
    cm.clear()
    with cm._lock:
        cm._epochs.clear()


def _key(prefix: str) -> str:
    """每个测试用独立 key（uuid 后缀），避免共享全局 cache 时 epoch 串扰。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ───────────────────────────────────────────────────────────
# 1. epoch 基础语义
# ───────────────────────────────────────────────────────────


def test_peek_invalidation_epoch_returns_zero_for_unknown_key(cache):
    """未触碰过的 key epoch = 0。"""
    assert cache.peek_invalidation_epoch(_key("never_set")) == 0


def test_set_does_not_change_epoch(cache):
    """set 不递增 epoch（只有 delete 递增）— 保持语义清晰。"""
    k = _key("k1")
    cache.set(k, "v1", ttl=60)
    assert cache.peek_invalidation_epoch(k) == 0
    cache.set(k, "v2", ttl=60)
    assert cache.peek_invalidation_epoch(k) == 0


def test_delete_increments_epoch(cache):
    """delete 递增 epoch。重复 delete（key 已不存在）epoch 不再递增 — 避免噪音。"""
    k = _key("k2")
    cache.set(k, "v1", ttl=60)
    assert cache.peek_invalidation_epoch(k) == 0
    cache.delete(k)
    assert cache.peek_invalidation_epoch(k) == 1
    cache.delete(k)  # 重复 delete，key 已不存在 → epoch 不再递增
    assert cache.peek_invalidation_epoch(k) == 1


def test_delete_unknown_key_returns_false_no_epoch_change(cache):
    """删除不存在的 key 返回 False，epoch 不变。"""
    k = _key("never_existed")
    assert cache.delete(k) is False
    assert cache.peek_invalidation_epoch(k) == 0


# ───────────────────────────────────────────────────────────
# 2. set(min_epoch=) 校验：stale write 防护
# ───────────────────────────────────────────────────────────


def test_set_with_min_epoch_blocks_stale_write(cache):
    """关键场景：拿到 epoch 后被 delete，再 set(min_epoch=old) 必须丢弃。

    这就是 R18 修复的 race：cache miss → 拿到 epoch=0 → SQL 跑 100ms → cache 被
    delete（epoch=1）→ SQL 完成 → set(min_epoch=0) 应被丢弃。
    """
    k = _key("dashboard")
    cache.set(k, {"stale": "initial"}, ttl=60)

    # T1: 拿到 epoch
    min_epoch = cache.peek_invalidation_epoch(k)
    assert min_epoch == 0

    # T2: SQL 跑（mock 跳过）期间 cache 被 delete（epoch=1）
    cache.delete(k)

    # T3: SQL 跑完，set 旧数据 → 应被丢弃
    wrote = cache.set(k, {"stale": "stale_write"}, ttl=60, min_epoch=min_epoch)
    assert wrote is False, f"stale write 应被丢弃，实获 {wrote}"
    assert cache.get(k) is None, "stale write 后 cache 仍应为空"


def test_set_with_current_min_epoch_succeeds(cache):
    """正常路径：拿到 epoch 后没被 delete，set(min_epoch=current) 成功。"""
    k = _key("dashboard")
    min_epoch = cache.peek_invalidation_epoch(k)
    # 模拟 SQL 跑（无 delete）
    wrote = cache.set(k, {"fresh": True}, ttl=60, min_epoch=min_epoch)
    assert wrote is True
    assert cache.get(k) == {"fresh": True}


def test_set_with_min_epoch_after_delete_uses_new_epoch(cache):
    """delete 后用新 epoch set 应成功（这是正常 refresh 路径）。"""
    k = _key("dashboard")
    cache.set(k, {"v1": True}, ttl=60)
    cache.delete(k)
    new_epoch = cache.peek_invalidation_epoch(k)
    assert new_epoch == 1
    wrote = cache.set(k, {"v2": True}, ttl=60, min_epoch=new_epoch)
    assert wrote is True
    assert cache.get(k) == {"v2": True}


def test_set_without_min_epoch_backward_compatible(cache):
    """默认 min_epoch=0 行为与旧版一致 — 不破坏既有调用点。

    这里场景：set 一个 key → delete → 再 set（不传 min_epoch）→ 应成功
    （min_epoch=0 当前 epoch=1 > 0，正常应被丢弃 — 但我们的"未传"语义 = "不校验"，
    允许老调用点不感知 epoch 系统也能写）
    """
    k = _key("legacy_call")
    cache.set(k, "v1", ttl=60)
    cache.delete(k)
    # 不传 min_epoch：保持向后兼容（旧 API 不感知 epoch 也能工作）
    wrote = cache.set(k, "v2", ttl=60)
    assert wrote is True
    assert cache.get(k) == "v2"


def test_get_or_set_respects_epoch_on_stale_write(cache):
    """v10 §4.1：get_or_set 在 factory 期间 epoch 被推进时不写入 stale 值。"""
    k = _key("get_or_set")
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        # 模拟 factory 执行期间并发 invalidate：先占位再 delete 推进 epoch
        cache.set(k, {"temp": True}, ttl=60)
        cache.delete(k)
        return {"v1": True}

    result = cache.get_or_set(k, factory, ttl=60)
    assert result == {"v1": True}
    assert calls["n"] == 1
    assert cache.get(k) is None
    assert cache.get_stats()["stale_writes"] >= 1


# ───────────────────────────────────────────────────────────
# 3. 端到端：dashboard handler 防护模拟
# ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_handler_drops_stale_write(cache):
    """模拟：dashboard handler 拿 epoch=0、SQL 跑期间 cache.delete → set 被丢弃。

    修复前：cache.set 会成功写入 T1 时刻的旧数据，覆盖 T2 的 invalidate 效果，
    导致后续 60s 内 dashboard 显示陈旧。
    修复后：set(min_epoch=0) 返回 False，cache 保持空，下一个 GET 走 SQL 重算。
    """
    k = _key("dashboard")
    # 模拟初始 cache 有值
    cache.set(k, {"v_before": True}, ttl=60)

    # 模拟 dashboard handler 流程
    min_epoch = cache.peek_invalidation_epoch(k)
    cache.delete(k)  # 模拟 SQL 期间的并发 delete
    # handler 写回
    wrote = cache.set(k, {"stale_value": True}, ttl=60, min_epoch=min_epoch)
    assert wrote is False
    assert cache.get(k) is None, "stale write 被丢弃后 cache 应保持空（不会被 60s 旧数据污染）"

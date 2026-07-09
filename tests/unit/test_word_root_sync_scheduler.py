"""词根自动同步调度测试。"""

from __future__ import annotations

import asyncio

import pytest

from dataworks_agent.governance import word_root_sync as mod


@pytest.mark.asyncio
async def test_word_root_sync_loop_runs_once(monkeypatch) -> None:
    calls = {"n": 0}

    async def _fake_sync(*args, **kwargs):
        calls["n"] += 1
        return {"status": "ok", "count": 1}

    monkeypatch.setattr(mod.settings, "word_root_auto_sync_enabled", True)
    monkeypatch.setattr(mod.settings, "word_root_sync_interval_seconds", 3600)
    monkeypatch.setattr(mod, "run_word_root_sync_once", _fake_sync)

    stop = asyncio.Event()

    async def _runner():
        task = asyncio.create_task(mod.word_root_sync_loop(stop))
        await asyncio.sleep(0.05)
        stop.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    await _runner()
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_word_root_sync_loop_disabled(monkeypatch) -> None:
    calls = {"n": 0}

    async def _fake_sync(*args, **kwargs):
        calls["n"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(mod.settings, "word_root_auto_sync_enabled", False)
    monkeypatch.setattr(mod, "run_word_root_sync_once", _fake_sync)

    stop = asyncio.Event()
    task = asyncio.create_task(mod.word_root_sync_loop(stop))
    await asyncio.sleep(0.05)
    stop.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["n"] == 0

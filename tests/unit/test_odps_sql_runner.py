"""ODPS SQL 原生客户端优先级测试。"""

from __future__ import annotations

from dataworks_agent.services.ods_di.field_infer import _registry_ddl_column


class TestRegistryDdlColumn:
    def test_min_uses_hour_ddl(self) -> None:
        assert _registry_ddl_column("min") == "ods_ddl_hour"

    def test_day_uses_day_ddl(self) -> None:
        assert _registry_ddl_column("day") == "ods_ddl_day"


class _FakeResultSet:
    def __init__(self, rows):
        self.rows = rows


class _FakeMaxCompute:
    def __init__(self, rows=None, raise_exc=False):
        self._rows = rows
        self._raise = raise_exc
        self.submitted = []

    async def submit_query(self, sql):
        self.submitted.append(sql)
        if self._raise:
            raise RuntimeError("mc down")
        return "inst"

    async def wait_and_fetch(self, instance):
        return _FakeResultSet(self._rows or [])


class TestRunOdpsQueryPreference:
    async def test_maxcompute_first(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        mc = _FakeMaxCompute(rows=[[1, "a"]])
        monkeypatch.setattr(app_state, "_maxcompute_client", mc)
        rows = await sql_runner.run_odps_query(bff=None, sql="SELECT 1")
        assert rows == [[1, "a"]]
        assert mc.submitted == ["SELECT 1"]

    async def test_falls_back_to_ida_when_mc_absent(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        monkeypatch.setattr(app_state, "_maxcompute_client", None)

        async def _fake_ida(bff, sql):
            return [["from_ida"]]

        monkeypatch.setattr(sql_runner, "run_ida_query", _fake_ida)
        assert await sql_runner.run_odps_query(bff=object(), sql="SELECT 1") == [["from_ida"]]

    async def test_falls_back_when_mc_raises(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        monkeypatch.setattr(app_state, "_maxcompute_client", _FakeMaxCompute(raise_exc=True))

        async def _fake_ida(bff, sql):
            return [["ida_after_mc_fail"]]

        monkeypatch.setattr(sql_runner, "run_ida_query", _fake_ida)
        assert await sql_runner.run_odps_query(bff=object(), sql="SELECT 1") == [
            ["ida_after_mc_fail"]
        ]

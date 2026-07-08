"""Unit tests for ODPS sql_runner MCP parsing."""

from __future__ import annotations

import json

from dataworks_agent.services.ods_di.field_infer import _registry_ddl_column
from dataworks_agent.services.ods_di.sql_runner import (
    _parse_job_code,
    _parse_mcp_body_list,
)


class TestRegistryDdlColumn:
    def test_min_uses_hour_ddl(self) -> None:
        assert _registry_ddl_column("min") == "ods_ddl_hour"

    def test_day_uses_day_ddl(self) -> None:
        assert _registry_ddl_column("day") == "ods_ddl_day"


class TestMcpParsing:
    def test_parse_job_code_from_json(self) -> None:
        raw = json.dumps({"job_code": "abc123"})
        assert _parse_job_code(raw) == "abc123"

    def test_parse_body_list_from_rows(self) -> None:
        raw = {
            "status": "SUCCESS",
            "rows": [{"ods_ddl_hour": "create table t (id bigint)"}],
        }
        body = _parse_mcp_body_list(raw)
        assert body == [["create table t (id bigint)"]]

    def test_parse_body_list_from_csv_result(self) -> None:
        raw = {
            "status": "SUCCESS",
            "result": 'ods_ddl_hour\n"CREATE TABLE t (id bigint)"',
        }
        body = _parse_mcp_body_list(raw)
        assert body == [["CREATE TABLE t (id bigint)"]]


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
        rows = await sql_runner.run_odps_query(bff=None, mcp=None, sql="SELECT 1")
        assert rows == [[1, "a"]]
        assert mc.submitted == ["SELECT 1"]

    async def test_falls_back_to_ida_when_mc_absent(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        monkeypatch.setattr(app_state, "_maxcompute_client", None)

        async def _fake_ida(bff, sql):
            return [["from_ida"]]

        monkeypatch.setattr(sql_runner, "run_ida_query", _fake_ida)
        rows = await sql_runner.run_odps_query(bff=object(), mcp=None, sql="SELECT 1")
        assert rows == [["from_ida"]]

    async def test_falls_back_when_mc_raises(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        monkeypatch.setattr(app_state, "_maxcompute_client", _FakeMaxCompute(raise_exc=True))

        async def _fake_ida(bff, sql):
            return [["ida_after_mc_fail"]]

        monkeypatch.setattr(sql_runner, "run_ida_query", _fake_ida)
        rows = await sql_runner.run_odps_query(bff=object(), mcp=None, sql="SELECT 1")
        assert rows == [["ida_after_mc_fail"]]

    async def test_mc_empty_rows_falls_back(self, monkeypatch):
        from dataworks_agent.services.ods_di import sql_runner
        from dataworks_agent.state import app_state

        monkeypatch.setattr(app_state, "_maxcompute_client", _FakeMaxCompute(rows=[]))

        async def _fake_ida(bff, sql):
            return [["ida_fallback"]]

        monkeypatch.setattr(sql_runner, "run_ida_query", _fake_ida)
        rows = await sql_runner.run_odps_query(bff=object(), mcp=None, sql="SELECT 1")
        assert rows == [["ida_fallback"]]

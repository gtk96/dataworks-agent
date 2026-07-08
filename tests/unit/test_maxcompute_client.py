"""MaxCompute_Client 单元测试（mock pyodps）— Requirement 4, 5, 12。"""

from __future__ import annotations

from typing import ClassVar

import pytest

from dataworks_agent.api_clients import maxcompute_client as mc_mod
from dataworks_agent.api_clients.destructive_guard import DestructiveOpBlockedError
from dataworks_agent.api_clients.maxcompute_client import (
    MaxComputeClient,
    MaxComputeError,
)
from dataworks_agent.auth import AliyunCredentials


# ── pyodps 假对象 ──
class _FakeColumn:
    def __init__(self, name, type_="string", comment=""):
        self.name = name
        self.type = type_
        self.comment = comment


class _FakeRecord:
    def __init__(self, columns, values):
        self._columns = [_FakeColumn(c) for c in columns]
        self._values = dict(zip(columns, values, strict=True))

    def __getitem__(self, key):
        return self._values[key]


class _FakeReader:
    def __init__(self, records, columns=None):
        self._records = records
        if columns is None and records:
            records_0 = records[0]
            if hasattr(records_0, "_columns"):
                columns = records_0._columns
        self.schema = _FakeSchema(columns or [])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._records)


class _FakeInstance:
    def __init__(self, records=None, fail_on_wait=False):
        self.id = "inst_123"
        self._records = records or []
        self._fail_on_wait = fail_on_wait
        self.waited = False

    def wait_for_success(self):
        self.waited = True
        if self._fail_on_wait:
            raise RuntimeError("ODPS-0130071 semantic error")

    def open_reader(self, tunnel=True):
        return _FakeReader(self._records)


class _FakeSchema:
    def __init__(self, columns, partitions=None):
        self.columns = columns
        self.partitions = partitions or []


class _FakeTable:
    def __init__(self, schema, comment=""):
        self.table_schema = schema
        self.comment = comment


class _FakeODPS:
    """记录构造参数、可编排 run_sql / get_table 行为。"""

    last_kwargs: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        _FakeODPS.last_kwargs = kwargs
        self.run_sql_calls: list[str] = []
        self._next_instance: _FakeInstance | None = None
        self._table: _FakeTable | None = None
        self._raise_on_run = False

    def run_sql(self, sql):
        self.run_sql_calls.append(sql)
        if self._raise_on_run:
            raise RuntimeError("submit rejected")
        return self._next_instance or _FakeInstance()

    def get_table(self, name):
        return self._table


@pytest.fixture
def creds():
    return AliyunCredentials(access_key_id="LTAI_id", access_key_secret="secret_1234")


@pytest.fixture
def patch_odps(monkeypatch):
    """把 maxcompute_client.ODPS 换成可控假对象，返回捕获实例的容器。"""
    holder: dict = {}

    def _factory(**kwargs):
        entry = _FakeODPS(**kwargs)
        holder["entry"] = entry
        return entry

    monkeypatch.setattr(mc_mod, "ODPS", _factory)
    return holder


def _make_client(creds) -> MaxComputeClient:
    return MaxComputeClient(
        creds=creds,
        endpoint="http://svc.maxcompute.aliyun.com/api",
        project="dataworks",
    )


class TestConnection:
    async def test_entry_built_with_akssk(self, creds, patch_odps):
        client = _make_client(creds)
        client._ensure_entry()
        kwargs = _FakeODPS.last_kwargs
        assert kwargs["access_id"] == "LTAI_id"
        assert kwargs["secret_access_key"] == "secret_1234"
        assert kwargs["project"] == "dataworks"
        assert kwargs["endpoint"] == "http://svc.maxcompute.aliyun.com/api"

    async def test_entry_cached(self, creds, patch_odps):
        client = _make_client(creds)
        first = client._ensure_entry()
        second = client._ensure_entry()
        assert first is second


class TestExecuteDdl:
    async def test_execute_ddl_success(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._next_instance = _FakeInstance()
        result = await client.execute_ddl("CREATE TABLE t (id bigint)")
        assert result.success is True
        assert result.instance_id == "inst_123"
        assert result.error is None

    async def test_execute_ddl_failure_returns_reason(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._next_instance = _FakeInstance(fail_on_wait=True)
        result = await client.execute_ddl("CREATE TABLE bad")
        assert result.success is False
        assert "semantic error" in result.error

    async def test_execute_ddl_submit_failure(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._raise_on_run = True
        result = await client.execute_ddl("CREATE TABLE t")
        assert result.success is False
        assert "submit rejected" in result.error


class TestQuery:
    async def test_submit_and_fetch(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        records = [
            _FakeRecord(["id", "name"], [1, "a"]),
            _FakeRecord(["id", "name"], [2, "b"]),
        ]
        entry._next_instance = _FakeInstance(records=records)
        instance = await client.submit_query("SELECT id, name FROM t")
        rs = await client.wait_and_fetch(instance)
        assert rs.columns == ["id", "name"]
        assert rs.rows == [[1, "a"], [2, "b"]]
        assert len(rs) == 2

    async def test_wait_and_fetch_failure_raises(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._next_instance = _FakeInstance(fail_on_wait=True)
        instance = await client.submit_query("SELECT 1")
        with pytest.raises(MaxComputeError) as exc:
            await client.wait_and_fetch(instance)
        assert "semantic error" in str(exc.value)


class TestSchema:
    async def test_get_table_schema(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._table = _FakeTable(
            _FakeSchema(
                columns=[
                    _FakeColumn("id", "bigint", "主键"),
                    _FakeColumn("name", "string", "名称"),
                ],
                partitions=[_FakeColumn("dt", "string", "分区日")],
            ),
            comment="测试表",
        )
        schema = await client.get_table_schema("dataworks.t")
        assert schema.table_name == "dataworks.t"
        assert schema.comment == "测试表"
        assert [c.name for c in schema.columns] == ["id", "name"]
        assert schema.columns[0].type == "bigint"
        assert schema.columns[0].comment == "主键"
        assert [c.name for c in schema.partition_keys] == ["dt"]


class TestDestructiveGuardWiring:
    async def test_execute_ddl_blocks_drop_prod_table(self, creds, patch_odps):
        client = _make_client(creds)
        with pytest.raises(DestructiveOpBlockedError):
            await client.execute_ddl("DROP TABLE dataworks.ord_order")

    async def test_submit_query_blocks_delete(self, creds, patch_odps):
        client = _make_client(creds)
        with pytest.raises(DestructiveOpBlockedError):
            await client.submit_query("DELETE FROM dataworks.t WHERE dt='20260101'")

    async def test_guard_runs_before_submit(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        with pytest.raises(DestructiveOpBlockedError):
            await client.submit_query("TRUNCATE TABLE dataworks.t")
        # 未触达 SDK run_sql
        assert entry.run_sql_calls == []

    async def test_allowed_sql_passes_guard(self, creds, patch_odps):
        client = _make_client(creds)
        entry = client._ensure_entry()
        entry._next_instance = _FakeInstance()
        result = await client.execute_ddl("CREATE TABLE dataworks.dwd_x (id bigint)")
        assert result.success is True

    async def test_guard_can_be_disabled(self, creds, patch_odps):
        client = MaxComputeClient(
            creds=creds,
            endpoint="http://svc/api",
            project="dataworks",
            enable_destructive_guard=False,
        )
        entry = client._ensure_entry()
        entry._next_instance = _FakeInstance()
        # 关闭守卫后 DROP 非 tmp 表也会提交（交由上层策略控制）
        result = await client.execute_ddl("DROP TABLE dataworks.ord_order")
        assert result.success is True

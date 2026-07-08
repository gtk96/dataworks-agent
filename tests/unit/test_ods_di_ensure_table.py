"""ensure_table(ods_di) 的 AK/SK MaxCompute 路径单测（Task 8a）。

验证：registry 查询走 mc、现有 DDL 走 mc.get_table_ddl、建表走 mc.execute_ddl 且剥离 DROP；
表已存在则比对不建表。
"""

from __future__ import annotations

from dataclasses import dataclass

from dataworks_agent.services.ods_di.ensure_table import ensure_table

REGISTRY_DDL = "drop table if exists foo;\ncreate table foo (id bigint, dt string);"


@dataclass
class _DDLResult:
    success: bool
    instance_id: str = "inst_1"
    error: str | None = None


class _RS:
    def __init__(self, rows):
        self.rows = rows


class FakeMC:
    def __init__(self, *, registry_ddl=REGISTRY_DDL, existing_ddl=None, ok=True):
        self._registry = registry_ddl
        self._existing = existing_ddl
        self._ok = ok
        self.executed: list[str] = []

    async def submit_query(self, sql):
        return "INST"

    async def wait_and_fetch(self, inst):
        return _RS([[self._registry]])

    async def get_table_ddl(self, table, *, project=None):
        return self._existing

    async def execute_ddl(self, sql):
        self.executed.append(sql)
        return _DDLResult(success=self._ok)


async def test_creates_table_via_mc_strips_drop():
    mc = FakeMC(existing_ddl=None)
    res = await ensure_table(
        None,
        None,
        datasource_name="ds",
        source_table_name="src",
        target_table="foo",
        granularity="day",
        mc_project="dataworks_dev",
        mc=mc,
    )
    assert res["status"] == "created"
    assert len(mc.executed) == 1
    ddl = mc.executed[0].lower()
    assert "drop table" not in ddl
    assert "create table" in ddl
    # inject 了 dev 前缀
    assert "dataworks_dev.foo" in ddl


async def test_existing_table_skips_create():
    # 表已存在（get_table_ddl 返回非空）→ 只比对、不建表
    existing = "create table dataworks_dev.foo (id bigint, dt string);"
    mc = FakeMC(existing_ddl=existing)
    res = await ensure_table(
        None,
        None,
        datasource_name="ds",
        source_table_name="src",
        target_table="foo",
        granularity="day",
        mc_project="dataworks_dev",
        mc=mc,
    )
    assert res["status"] in ("exists", "incompatible")
    assert mc.executed == []  # 存在即不建表


async def test_registry_miss_returns_failed():
    mc = FakeMC(registry_ddl="")
    res = await ensure_table(
        None,
        None,
        datasource_name="ds",
        source_table_name="src",
        target_table="foo",
        granularity="day",
        mc_project="dataworks_dev",
        mc=mc,
    )
    assert res["status"] == "failed"

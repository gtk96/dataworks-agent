"""MaxCompute_Client — 基于 pyodps 的执行底座（Requirement 4, 5, 12）。

承接原 bff_client 的 SQL 执行能力：
- execute_ddl      ← 替代 bff.execute_ddl（原走 MCP）
- submit_query     ← 替代 bff.execute_sql / execute_sql_ida
- wait_and_fetch   ← 替代 bff.wait_job + get_query_result
- get_table_schema ← 逆向建模取结构（Reverse_Modeling）

pyodps 为同步库；本类将阻塞调用统一包进 asyncio.to_thread，避免阻塞 FastAPI
事件循环。AK/SK 由 Auth_Provider 提供，全类复用同一份凭证。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from odps import ODPS

from dataworks_agent.api_clients.destructive_guard import guard_sql
from dataworks_agent.auth import AliyunCredentials

if TYPE_CHECKING:
    from odps.models import Instance

logger = logging.getLogger(__name__)


class MaxComputeError(RuntimeError):
    """MaxCompute 作业执行失败。"""


@dataclass
class JobResult:
    """一次 DDL / 作业执行的结构化结果。"""

    success: bool
    instance_id: str = ""
    error: str | None = None


@dataclass
class ResultSet:
    """查询结果集 — 列名 + 行数据。"""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass
class ColumnSchema:
    name: str
    type: str
    comment: str = ""


@dataclass
class TableSchema:
    """逆向建模用的表结构快照。"""

    table_name: str
    columns: list[ColumnSchema] = field(default_factory=list)
    partition_keys: list[ColumnSchema] = field(default_factory=list)
    comment: str = ""


class MaxComputeClient:
    """MaxCompute pyodps 客户端。"""

    def __init__(
        self,
        creds: AliyunCredentials,
        endpoint: str,
        project: str,
        *,
        enable_destructive_guard: bool = True,
    ) -> None:
        self._creds = creds
        self._endpoint = endpoint
        self._project = project
        self._entry: ODPS | None = None
        self._enable_destructive_guard = enable_destructive_guard

    def _guard(self, sql: str) -> None:
        """执行提交前的破坏性操作拦截（Requirement 36.7）。"""
        if self._enable_destructive_guard:
            guard_sql(sql)

    def _ensure_entry(self) -> ODPS:
        """惰性创建 ODPS 入口对象（AK/SK 鉴权）。"""
        if self._entry is None:
            self._entry = ODPS(
                access_id=self._creds.access_key_id,
                secret_access_key=self._creds.access_key_secret,
                project=self._project,
                endpoint=self._endpoint,
            )
        return self._entry

    async def execute_ddl(self, sql: str) -> JobResult:
        """执行 DDL（建表 / ALTER 等），轮询至终态。

        Requirement 4.3/4.5：提交作业并等待到成功或失败终态，失败返回原因。
        Requirement 36.7：提交前经 DestructiveOpGuard 拦截破坏性操作。
        """
        self._guard(sql)
        try:
            entry = self._ensure_entry()
            instance = await asyncio.to_thread(entry.run_sql, sql)
            await asyncio.to_thread(instance.wait_for_success)
            return JobResult(success=True, instance_id=str(instance.id))
        except Exception as e:
            logger.warning("MaxCompute execute_ddl 失败: %s", e)
            return JobResult(success=False, error=str(e))

    async def submit_query(self, sql: str) -> Instance:
        """提交查询作业（非阻塞提交），返回 Instance 供 wait_and_fetch 消费。

        Requirement 36.7：提交前经 DestructiveOpGuard 拦截破坏性操作。
        """
        self._guard(sql)
        entry = self._ensure_entry()
        return await asyncio.to_thread(entry.run_sql, sql)

    async def wait_and_fetch(self, instance: Instance) -> ResultSet:
        """等待作业到达终态并取结构化结果集。

        Raises:
            MaxComputeError: 作业失败时（含失败原因）。
        """
        try:
            await asyncio.to_thread(instance.wait_for_success)
        except Exception as e:
            inst_id = getattr(instance, "id", "?")
            raise MaxComputeError(f"作业执行失败 (instance={inst_id}): {e}") from e

        return await asyncio.to_thread(self._read_instance, instance)

    @staticmethod
    def _read_instance(instance: Instance) -> ResultSet:
        """从 Instance 读取结果集（同步，在 to_thread 中运行）。"""
        columns: list[str] = []
        rows: list[list[Any]] = []
        with instance.open_reader(tunnel=True) as reader:
            for record in reader:
                if not columns:
                    columns = [col.name for col in reader.schema.columns]
                rows.append([record[c] for c in columns])
        return ResultSet(columns=columns, rows=rows)

    async def table_exists(self, table: str, *, project: str | None = None) -> bool:
        """判断表是否存在（仅元数据，不读数据行）。用于建表前的存在性检查。"""
        entry = self._ensure_entry()
        if project:
            return await asyncio.to_thread(entry.exist_table, table, project)
        return await asyncio.to_thread(entry.exist_table, table)

    async def get_table_ddl(self, table: str, *, project: str | None = None) -> str | None:
        """取现有表的 CREATE TABLE DDL 文本（不存在返回 None）。用于结构兼容性比对。"""
        entry = self._ensure_entry()

        def _ddl() -> str | None:
            exists = entry.exist_table(table, project) if project else entry.exist_table(table)
            if not exists:
                return None
            t = entry.get_table(table, project=project) if project else entry.get_table(table)
            return t.get_ddl()

        try:
            return await asyncio.to_thread(_ddl)
        except Exception as e:
            logger.debug("get_table_ddl(%s) 失败: %s", table, e)
            return None

    async def get_table_schema(self, table: str) -> TableSchema:
        """取指定表的结构（字段 / 类型 / 注释 / 分区），用于逆向建模。

        仅读取元数据，不读取数据行（Requirement 12.6）。
        """
        entry = self._ensure_entry()
        return await asyncio.to_thread(self._read_schema, entry, table)

    @staticmethod
    def _read_schema(entry: ODPS, table: str) -> TableSchema:
        t = entry.get_table(table)
        if t is None:
            raise ValueError("table not found: " + table)
        schema = getattr(t, "table_schema", None) or t.schema
        cols = [
            ColumnSchema(name=c.name, type=str(c.type), comment=c.comment or "")
            for c in schema.columns
        ]
        parts = [
            ColumnSchema(name=c.name, type=str(c.type), comment=c.comment or "")
            for c in getattr(schema, "partitions", []) or []
        ]
        return TableSchema(
            table_name=table,
            columns=cols,
            partition_keys=parts,
            comment=getattr(t, "comment", "") or "",
        )

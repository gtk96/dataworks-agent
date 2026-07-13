"""TableDiscovery — 通过原生 MaxCompute/BFF 发现内部表与外部数据源。"""

from __future__ import annotations

import logging
import time

from dataworks_agent.config import settings
from dataworks_agent.schemas import DataSourceInfo, TableInfo, TableStructure

logger = logging.getLogger(__name__)

CACHE_TTL = 600  # 10 分钟


class TableDiscovery:
    """Wizard 步骤 1: 源表搜索/选择。"""

    def __init__(self) -> None:
        self._cache: list[TableInfo] = []
        self._cache_time: float = 0

    def _cache_valid(self) -> bool:
        return bool(self._cache) and (time.time() - self._cache_time) < CACHE_TTL

    async def search_tables(self, keyword: str, layer: str = "ODS") -> list[TableInfo]:
        """模糊搜索 MC 内部表。"""
        if self._cache_valid():
            return [t for t in self._cache if keyword.lower() in t.name.lower()]

        from dataworks_agent.mcp.operations import list_tables

        try:
            tables = await list_tables(settings.dataworks_prod_schema, keyword=f"{layer.lower()}_%")
            self._cache = [
                TableInfo(
                    name=t.get("name", t.get("table_name", "")),
                    schema_name=t.get("schema", settings.dataworks_prod_schema),
                    layer=layer,
                )
                for t in (tables or [])
            ]
            self._cache_time = time.time()
            return [t for t in self._cache if keyword.lower() in t.name.lower()]
        except Exception as e:
            logger.warning("搜索表失败: %s", e)
            return []

    async def get_table_structure(self, table: str) -> TableStructure:
        """获取表字段详情 — MaxCompute 元数据优先，BFF IDA 回退。"""
        from dataworks_agent.mcp.operations import get_table_ddl

        # 支持 schema.table 格式
        if "." in table:
            schema, bare_table = table.split(".", 1)
        else:
            schema = settings.dataworks_prod_schema
            bare_table = table

        full_name = f"odps.{schema}.{bare_table}"
        ddl = ""
        try:
            raw = await get_table_ddl(full_name)
            if isinstance(raw, dict):
                ddl = raw.get("ddl", "")
            elif isinstance(raw, str):
                ddl = raw
        except Exception as exc:
            logger.debug("原生 get_table_ddl 失败: %s", exc)

        if ddl and "CREATE TABLE" in ddl.upper():
            return self._parse_ddl_to_structure(bare_table, ddl)

        # BFF 回退：查 information_schema
        logger.info("MaxCompute 元数据不可用，尝试 BFF 查询 %s.%s 字段", schema, bare_table)
        return await self._query_columns_via_bff(f"{schema}.{bare_table}")

    async def list_data_sources(self, keyword: str = "") -> list[DataSourceInfo]:
        """获取 DataWorks 数据集成数据源列表。"""
        from dataworks_agent.state import app_state

        bff = getattr(app_state, "_bff_client", None)
        if not bff:
            return []

        sources = await bff.list_datasources(keyword)
        return [
            DataSourceInfo(
                name=s.get("datasourceName", s.get("name", "")),
                ds_type=s.get("datasourceType", s.get("type", "")),
                connection_info=s,
            )
            for s in sources
            if s.get("datasourceType", s.get("type", "")) not in ("odps", "analyticsdb")
        ]

    async def list_source_tables(self, ds_name: str, ds_type: str) -> list[str]:
        """列出数据源下的表。"""
        from dataworks_agent.state import app_state

        bff = getattr(app_state, "_bff_client", None)
        if not bff:
            return []

        tables = await bff.list_datasource_tables(ds_name, ds_type)
        return [t.get("tableName", t.get("table_name", "")) for t in tables]

    def _parse_ddl_to_structure(self, table_name: str, ddl: str) -> TableStructure:
        """从 DDL 文本解析字段结构。"""
        from dataworks_agent.schemas import ColumnDef

        columns = []
        partitions = []
        in_partitions = False

        for line in ddl.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue

            if "CREATE TABLE" in line.upper():
                continue
            if "PARTITIONED BY" in line.upper():
                in_partitions = True
                continue

            # 简单解析: 字段名 类型 COMMENT '注释'
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0].strip('`"')
                dtype = parts[1].strip(",")
                comment = ""
                if "COMMENT" in line.upper():
                    idx = line.upper().index("COMMENT") + 7
                    comment = line[idx:].strip().strip("'\"")
                col = ColumnDef(name=name, type=dtype, comment=comment)
                if in_partitions:
                    col.is_partition = True
                    partitions.append(name)
                else:
                    columns.append(col)

        return TableStructure(
            table_name=table_name,
            columns=columns,
            partition_keys=partitions,
            source_format="json" if "json_data" in ddl.lower() else "structured",
        )

    async def _query_columns_via_bff(self, table: str) -> TableStructure:
        """获取源表结构：AK/SK MaxCompute get_table_ddl 优先，降级 bff show create table。"""
        from dataworks_agent.state import app_state

        # 支持 schema.table 格式
        if "." in table:
            schema, bare_table = table.split(".", 1)
        else:
            schema = settings.dataworks_prod_schema
            bare_table = table

        # AK/SK MaxCompute 优先（不依赖 DataMap 权限）
        mc = getattr(app_state, "_maxcompute_client", None)
        if mc is not None:
            try:
                ddl = await mc.get_table_ddl(bare_table, project=schema)
            except Exception as exc:
                logger.debug("MaxCompute get_table_ddl %s.%s: %s", schema, bare_table, exc)
                ddl = None
            if ddl and "CREATE TABLE" in ddl.upper():
                return self._parse_ddl_to_structure(bare_table, ddl)

        # 降级：bff show create table
        bff = getattr(app_state, "_bff_client", None)
        if not bff:
            raise ValueError("执行客户端不可用，无法查询源表字段")

        full_table = f"{schema}.{bare_table}"
        sql = f"show create table {full_table}"
        job_code = await bff.execute_sql(sql)
        if not job_code:
            raise ValueError(f"无法查询 {full_table} 的 DDL: {bff.last_error or '未知错误'}")
        if not await bff.wait_job(job_code):
            raise ValueError(f"查询 {full_table} DDL 失败: {bff.last_error or '执行失败'}")
        result = await bff.get_query_result(job_code)
        body = (result or {}).get("bodyList") or []
        if not body or not body[0]:
            raise ValueError(f"未获取到 {full_table} 的 DDL")

        ddl = str(body[0][0]).strip()
        return self._parse_ddl_to_structure(bare_table, ddl)

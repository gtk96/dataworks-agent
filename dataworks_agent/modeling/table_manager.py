"""TableManager — 通过 MCP execute_ddl 建表 + 轮询确认。"""

from __future__ import annotations

import asyncio
import logging

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel
from dataworks_agent.mcp.operations import execute_ddl, get_table_ddl

logger = logging.getLogger(__name__)


class TableManager:
    """建表管理器 — MCP 通道直接执行 DDL。"""

    async def create_tables(self, task_id: str) -> None:
        """执行 dev + prod 双表 DDL。"""
        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task:
                raise RuntimeError(f"任务 {task_id} 不存在")
            ddl_dev = task.ddl_dev
            ddl_prod = task.ddl_prod
            target_table = task.target_table

        # 1. 建 dev 表
        logger.info("建 dev 表: %s", target_table)
        result = await execute_ddl(ddl_dev)
        if not result.get("success", False):
            raise RuntimeError(f"建 dev 表失败: {result}")

        # 轮询确认
        dev_guid = f"odps.{self._get_config().dataworks_dev_schema}.{target_table}"
        await self._wait_for_table(dev_guid)

        # 2. 建 prod 表
        logger.info("建 prod 表: %s", target_table)
        result = await execute_ddl(ddl_prod)
        if not result.get("success", False):
            raise RuntimeError(f"建 prod 表失败: {result}")

        prod_guid = f"odps.{self._get_config().dataworks_prod_schema}.{target_table}"
        await self._wait_for_table(prod_guid)

        # 记录建表成功
        self._record_table_creation(task_id, target_table)

        # 增量备份
        from dataworks_agent.db.backup import incremental_backup_on_event

        await incremental_backup_on_event("TableCreated", task_id)

    async def _wait_for_table(self, table_guid: str, timeout: float = 30.0) -> None:
        """轮询 get_table_ddl 直到表可见。"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                ddl = await get_table_ddl(table_guid)
                if ddl and "CREATE TABLE" in ddl.upper():
                    logger.info("表确认可见: %s", table_guid)
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
        raise TimeoutError(f"表 {table_guid} 在 {timeout}s 内不可见")

    def _record_table_creation(self, task_id: str, table_name: str) -> None:
        """记录建表事件到 table_definitions 表。"""
        from dataworks_agent.db.models import TableDefinitionModel

        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task:
                return
            entry = TableDefinitionModel(
                table_name=table_name,
                schema_name=self._get_config().dataworks_dev_schema,
                layer=task.target_layer,
                columns_json=task.columns_json,
                ddl_text=task.ddl_dev,
                created_by_ip=task.created_by_ip,
            )
            db.add(entry)
            db.commit()

    @staticmethod
    def _get_config():
        from dataworks_agent.config import settings

        return settings

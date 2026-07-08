"""SyncEngine — dev→prod 同步引擎（DDL 差异对比 + ALTER + INSERT + 事务补偿回滚）。"""

from __future__ import annotations

import logging

from dataworks_agent.config import settings
from dataworks_agent.schemas import SyncDiffResponse

logger = logging.getLogger(__name__)


class SyncCatastrophicError(Exception):
    """同步失败且回滚也失败 — 需人工介入。"""

    pass


class SyncRollbackError(Exception):
    """同步失败但 DDL 已回滚。"""

    pass


class SyncEngine:
    """双环境同步引擎。"""

    async def sync_table(self, table_name: str, project_id: int | None = None) -> SyncDiffResponse:
        """获取 dev/prod 差异对比。"""
        from dataworks_agent.mcp.operations import get_table_ddl

        dev_guid = f"odps.{settings.dataworks_dev_schema}.{table_name}"
        prod_guid = f"odps.{settings.dataworks_prod_schema}.{table_name}"

        dev_ddl = await get_table_ddl(dev_guid)
        prod_ddl = await get_table_ddl(prod_guid)

        diff = self._compare_ddl(dev_ddl, prod_ddl)

        alter_sql = ""
        if diff:
            alter_sql = self._generate_alter_sql(diff, table_name)

        return SyncDiffResponse(
            has_changes=bool(diff),
            diff_details=diff,
            alter_sql=alter_sql,
            requires_user_action=bool(diff),
        )

    async def execute_sync(self, table_name: str) -> dict:
        """执行同步操作 — ALTER + INSERT，带事务补偿。"""
        from dataworks_agent.mcp.operations import execute_ddl, get_table_ddl

        prod_guid = f"odps.{settings.dataworks_prod_schema}.{table_name}"

        # 1. ALTER 前备份 prod 表 DDL
        prod_ddl_snapshot = await get_table_ddl(prod_guid)

        # 2. 获取差异
        diff_result = await self.sync_table(table_name)
        if not diff_result.has_changes:
            return {"status": "no_changes", "message": "dev 和 prod 已一致"}

        # 3. 执行 ALTER
        try:
            alter_result = await execute_ddl(diff_result.alter_sql)
            if not alter_result.get("success"):
                return {"status": "failed", "step": "alter", "log": str(alter_result)}
        except Exception as e:
            logger.error("ALTER 执行失败: %s", e)
            return {"status": "failed", "step": "alter", "error": str(e)}

        # 4. INSERT 数据同步
        insert_sql = f"INSERT OVERWRITE TABLE {settings.dataworks_prod_schema}.{table_name} SELECT * FROM {settings.dataworks_dev_schema}.{table_name}"
        try:
            from dataworks_agent.mcp.operations import submit_query

            await submit_query(insert_sql)
        except Exception as e:
            # 回滚 ALTER
            try:
                rollback_ddl = self._generate_rollback_ddl(prod_ddl_snapshot, table_name)
                await execute_ddl(rollback_ddl)
                logger.error("同步失败，表结构已回滚: %s", e)
                raise SyncRollbackError(f"数据同步失败(已回滚DDL): {e}")
            except SyncRollbackError:
                raise
            except Exception as rollback_err:
                logger.critical("回滚 DDL 也失败了！快照: %s", prod_ddl_snapshot)
                raise SyncCatastrophicError(f"数据同步失败且回滚失败: {e} | {rollback_err}") from e

        return {"status": "completed", "table": table_name}

    def _compare_ddl(self, dev_ddl: str, prod_ddl: str) -> list[dict]:
        """对比两张表的 DDL 差异。"""
        dev_cols = self._parse_columns(dev_ddl)
        prod_cols = self._parse_columns(prod_ddl)

        diff = []
        dev_names = {c["name"] for c in dev_cols}
        prod_names = {c["name"] for c in prod_cols}

        # 新增字段
        for name in dev_names - prod_names:
            col = next(c for c in dev_cols if c["name"] == name)
            diff.append(
                {
                    "type": "add",
                    "name": name,
                    "dtype": col["type"],
                    "comment": col.get("comment", ""),
                }
            )

        # 删除字段
        for name in prod_names - dev_names:
            col = next(c for c in prod_cols if c["name"] == name)
            diff.append({"type": "drop", "name": name})

        # 类型变更
        for name in dev_names & prod_names:
            dev_col = next(c for c in dev_cols if c["name"] == name)
            prod_col = next(c for c in prod_cols if c["name"] == name)
            if dev_col["type"] != prod_col["type"]:
                diff.append(
                    {
                        "type": "modify",
                        "name": name,
                        "old_type": prod_col["type"],
                        "new_type": dev_col["type"],
                    }
                )

        return diff

    def _parse_columns(self, ddl: str) -> list[dict]:
        """从 DDL 文本解析字段列表。"""
        cols = []
        if not ddl:
            return cols
        in_block = False
        for line in ddl.split("\n"):
            line = line.strip().rstrip(",")
            if "CREATE TABLE" in line.upper():
                in_block = True
                continue
            if "PARTITIONED BY" in line.upper() or "LIFECYCLE" in line.upper():
                break
            if not in_block or line.startswith("--") or not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                cols.append(
                    {"name": parts[0].strip('`"'), "type": parts[1].strip(","), "comment": ""}
                )
        return cols

    def _generate_alter_sql(self, diff: list[dict], table_name: str = "TABLE_NAME") -> str:
        """从差异列表生成 ALTER TABLE 语句。"""
        from dataworks_agent.config import settings

        lines = [f"ALTER TABLE {settings.dataworks_prod_schema}.{table_name}"]
        for d in diff:
            if d["type"] == "add":
                lines.append(f"  ADD COLUMNS ({d['name']} {d['dtype']})")
            elif d["type"] == "drop":
                lines.append(f"  DROP COLUMNS ({d['name']})")
            elif d["type"] == "modify":
                lines.append(f"  CHANGE COLUMN {d['name']} {d['name']} {d['new_type']}")
        return "\n".join(lines) + ";"

    def _generate_rollback_ddl(self, snapshot_ddl: str, table_name: str) -> str:
        """生成回滚 DDL: DROP TABLE IF EXISTS + CREATE TABLE。"""
        if not snapshot_ddl:
            return f"DROP TABLE IF EXISTS {settings.dataworks_prod_schema}.{table_name};"
        return snapshot_ddl

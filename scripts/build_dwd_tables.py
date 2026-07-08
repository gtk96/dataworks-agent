"""从 DDL 文件提取 CREATE TABLE,在 dataworks / dataworks_dev 两个 schema 下建表。"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("build_dwd_tables")

DDL_DIR = Path(r"E:\dw-modeling-template\sql\order-fulfillment\dwd\ddl")
MC_PROD = "dataworks"
MC_DEV = "dataworks_dev"


def parse_ddl_file(content: str) -> dict[str, str]:
    """返回 {table_name: create_table_ddl}。"""
    result: dict[str, str] = {}
    current_table: str | None = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        line_stripped = line.strip()
        drop_match = re.match(
            r"drop\s+table\s+if\s+exists\s+\S+\.(\w+)", line_stripped, re.IGNORECASE
        )
        if drop_match:
            if current_table and current_lines:
                result[current_table] = "\n".join(current_lines).strip()
            current_table = drop_match.group(1)
            current_lines = [line]
            continue

        if current_table:
            current_lines.append(line)
            if line_stripped == ";":
                result[current_table] = "\n".join(current_lines).strip()
                current_table = None
                current_lines = []

    if current_table and current_lines:
        result[current_table] = "\n".join(current_lines).strip()
    return result


async def exec_ddl(bff: DataWorksClient, sql: str) -> bool:
    job = await bff.execute_sql(sql)
    if not job:
        logger.warning("execute_sql 失败: %s", bff.last_error)
        return False
    ok = await bff.wait_job(job, max_retry=15, interval=2)
    if not ok:
        err = bff.last_error or ""
        logger.warning("DDL 失败: %s", err[:200])
    return ok


async def main() -> None:
    bff = DataWorksClient()

    # 收集所有表的 DDL
    all_ddls: dict[str, str] = {}
    for f in sorted(DDL_DIR.glob("*.sql")):
        content = f.read_text(encoding="utf-8")
        all_ddls.update(parse_ddl_file(content))
    logger.info("共 %d 张 DWD 表", len(all_ddls))

    ok = failed = 0
    for table_name, ddl in sorted(all_ddls.items()):
        for schema in (MC_DEV, MC_PROD):
            ddl_s = (
                ddl.replace(
                    f"drop table if exists {table_name}",
                    f"drop table if exists {schema}.{table_name}",
                ).replace(
                    f"create table {table_name}",
                    f"create table {schema}.{table_name}",
                )
            )
            success = await exec_ddl(bff, ddl_s)
            tag = "OK" if success else "FAIL"
            print(f"  [{tag}] {schema}.{table_name}")
            if success:
                ok += 1
            else:
                failed += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())

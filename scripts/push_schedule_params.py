"""把更新后的调度参数(包含 gmtdate_last2h)推送到已部署的 ofc/oms ODS 节点。"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS, generate_cron, get_cycle_type

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_schedule")


NODE_BASE = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"
SCHEDULE_MINUTE = 1


def extract_table_names(dml_content: str) -> list[str]:
    pattern = r"insert into cda\.(ods_hl_\w+__\w+_hour)\b"
    return list(dict.fromkeys(re.findall(pattern, dml_content, re.IGNORECASE)))


async def main() -> None:
    bff = DataWorksClient()

    dml_dir = Path(r"E:\dw-modeling-template\sql\order-fulfillment\ods\dml")
    files = sorted(dml_dir.glob("ods_hl_ofc__*_dml.sql")) + sorted(
        dml_dir.glob("ods_hl_oms__*_dml.sql")
    )
    if not files:
        raise FileNotFoundError(f"未找到 DML 文件: {dml_dir}")

    tables: list[str] = []
    for f in files:
        tables.extend(extract_table_names(f.read_text(encoding="utf-8")))
    logger.info("共需更新 %d 个节点的调度参数", len(tables))

    cron = generate_cron("hour", minute=SCHEDULE_MINUTE)
    cycle_type = get_cycle_type("hour")
    parameters = HOURLY_SQL_PARAMETERS

    ok = 0
    failed = 0
    for table_name in tables:
        node_path = f"{NODE_BASE}/{table_name}"
        uuid = await bff.get_node_uuid_by_path(node_path)
        if not uuid:
            print(f"  FAIL: {node_path} (未找到节点)")
            failed += 1
            continue

        success = await bff.update_vertex(
            uuid,
            {
                "trigger": {
                    "type": "Scheduler",
                    "cron": cron,
                    "cycleType": cycle_type,
                    "startTime": "1970-01-01 00:00:00",
                    "endTime": "9999-01-01 00:00:00",
                    "timezone": "Asia/Shanghai",
                },
                "script": {"parameters": parameters},
                "strategy": {"instanceMode": "Immediately"},
                "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
            },
        )

        status = "OK" if success else f"FAIL ({bff.last_error or '?'})"
        print(f"  {status}: {node_path} (uuid={uuid})")
        if success:
            ok += 1
        else:
            failed += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())

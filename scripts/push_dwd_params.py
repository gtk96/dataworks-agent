"""把 gmtdate_last1d 调度参数推到 DWD 节点的 script.parameters。"""
from __future__ import annotations

import asyncio
import logging

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming.schedule import DWD_SQL_PARAMETERS, generate_cron, get_cycle_type

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dwd_params")

DWD_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD"
SCHEDULE_MINUTE = 1


async def fetch_dwd_uuids(bff: DataWorksClient) -> dict[str, str]:
    r = await bff._get(
        "ide/searchFiles",
        {"projectId": bff.project_id, "keyword": "dwd_ord_", "scene": "DATAWORKS_PROJECT", "pageSize": 100},
    )
    out: dict[str, str] = {}
    for h in (r.get("data") or {}).get("data", {}).get("hits", []) or []:
        path = h.get("path", "")
        if path.startswith(DWD_BASE):
            name = h.get("name", "").replace(".sql", "")
            v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if v_uuid:
                out[name] = v_uuid
    return out


async def main() -> None:
    bff = DataWorksClient()

    logger.info("抓取 DWD 节点 uuid ...")
    dwd_uuids = await fetch_dwd_uuids(bff)
    logger.info("DWD 节点数: %d", len(dwd_uuids))

    cron = generate_cron("hour", minute=SCHEDULE_MINUTE)
    cycle_type = get_cycle_type("hour")
    parameters = DWD_SQL_PARAMETERS

    ok = failed = 0
    for table_name, uuid in dwd_uuids.items():
        payload = {
            "projectId": bff.project_id,
            "uuid": str(uuid),
            "instanceMode": "Immediately",
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
        }
        resp = await bff._post("ide/updateVertex", payload)
        success = resp.get("code") == 200
        status = "OK" if success else f"FAIL ({resp.get('message', '?')})"
        print(f"  {status}: {table_name} (uuid={uuid})")
        if success:
            ok += 1
        else:
            failed += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())

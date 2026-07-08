"""把 Daily 调度参数(bizdate)推到 01_DIM 目录下已建的 DIM 节点。"""
from __future__ import annotations

import asyncio
import logging

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.naming.schedule import get_schedule_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dim_params")

DIM_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM"


async def fetch_dim_uuids(bff: DataWorksClient) -> dict[str, str]:
    r = await bff._get(
        "ide/searchFiles",
        {"projectId": bff.project_id, "keyword": "dim_ord_", "scene": "DATAWORKS_PROJECT", "pageSize": 100},
    )
    out: dict[str, str] = {}
    for h in (r.get("data") or {}).get("data", {}).get("hits", []) or []:
        if (h.get("path") or "").startswith(DIM_BASE):
            name = h.get("name", "").replace(".sql", "")
            v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if v_uuid:
                out[name] = v_uuid
    return out


async def main() -> None:
    bff = DataWorksClient()

    logger.info("抓取 DIM 节点 uuid ...")
    dim_uuids = await fetch_dim_uuids(bff)
    logger.info("DIM 节点数: %d", len(dim_uuids))

    sched = get_schedule_config("all")

    ok = failed = 0
    for table_name, uuid in dim_uuids.items():
        payload = {
            "projectId": bff.project_id,
            "uuid": str(uuid),
            "instanceMode": "Immediately",
            "trigger": {
                "type": "Scheduler",
                "cron": sched["cron"],
                "cycleType": sched["cycle_type"],
                "startTime": "1970-01-01 00:00:00",
                "endTime": "9999-01-01 00:00:00",
                "timezone": "Asia/Shanghai",
            },
            "script": {"parameters": sched["parameters"]},
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

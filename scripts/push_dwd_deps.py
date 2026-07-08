"""给 DWD 节点配依赖(Normal 类型, output=上游 ODS uuid)+ outputs。

依赖通过 ide/addNodeDependencies 接口(PUT),不是 updateVertex。
"""

from __future__ import annotations

import asyncio
import logging

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dwd_deps")

DWD_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD"
ODS_BASE = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"


async def fetch_uuids(bff: DataWorksClient, keyword: str, path_prefix: str) -> dict[str, str]:
    r = await bff._get(
        "ide/searchFiles",
        {
            "projectId": bff.project_id,
            "keyword": keyword,
            "scene": "DATAWORKS_PROJECT",
            "pageSize": 100,
        },
    )
    out: dict[str, str] = {}
    for h in (r.get("data") or {}).get("data", {}).get("hits", []) or []:
        path = h.get("path", "")
        if path.startswith(path_prefix):
            name = h.get("name", "").replace(".sql", "")
            v_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if v_uuid:
                out[name] = v_uuid
    return out


def dwd_to_ods(dwd_table: str) -> str:
    """dwd_ord_ofc_s_order_hour -> ods_hl_ofc__s_order_hour"""
    import re as _re

    m = _re.match(r"^dwd_ord_(ofc|oms|ms)_(.+_hour)$", dwd_table)
    if not m:
        return ""
    return f"ods_hl_{m.group(1)}__{m.group(2)}"


async def add_node_dependencies(bff: DataWorksClient, target_uuid: str, deps: list[dict]) -> bool:
    """调用 ide/addNodeDependencies (PUT) 增加节点依赖。"""
    payload = {
        "projectId": bff.project_id,
        "uuid": str(target_uuid),
        "dependencies": deps,
    }
    resp = await bff._put("ide/addNodeDependencies", payload)
    return resp.get("code") == 200


async def main() -> None:
    bff = DataWorksClient()

    logger.info("抓取 ODS 和 DWD 节点 uuid ...")
    ods_uuids = await fetch_uuids(bff, "ods_hl_", ODS_BASE)
    dwd_uuids = await fetch_uuids(bff, "dwd_ord_", DWD_BASE)
    logger.info("ODS 节点: %d, DWD 节点: %d", len(ods_uuids), len(dwd_uuids))

    ok_deps = ok_out = failed = 0

    for dwd_table, dwd_uuid in dwd_uuids.items():
        ods_table = dwd_to_ods(dwd_table)
        ods_uuid = ods_uuids.get(ods_table, "")

        # 1. dependencies: 上游 ODS + 自依赖 (CrossCycleDependsOnSelf)
        deps: list[dict] = [{"type": "CrossCycleDependsOnSelf"}]
        if ods_uuid:
            deps.insert(0, {"type": "Normal", "output": ods_uuid, "sourceType": "System"})
        dep_ok = await add_node_dependencies(bff, dwd_uuid, deps)

        # 2. outputs: 节点产出
        out_payload = {
            "projectId": bff.project_id,
            "uuid": str(dwd_uuid),
            "instanceMode": "Immediately",
            "outputs": {
                "nodeOutputs": [
                    {
                        "data": str(dwd_uuid),
                        "refTableName": dwd_table,
                        "artifactType": "NodeOutput",
                        "sourceType": "System",
                        "isDefault": True,
                    }
                ]
            },
        }
        out_resp = await bff._post("ide/updateVertex", out_payload)
        out_ok = out_resp.get("code") == 200

        if dep_ok:
            ok_deps += 1
        if out_ok:
            ok_out += 1
        if not (dep_ok and out_ok):
            failed += 1
            print(f"  FAIL: {dwd_table} (dep={dep_ok}, out={out_ok}, ods={ods_table})")
        else:
            print(f"  OK: {dwd_table} <- {ods_table}")

    await bff.close()
    print(
        f"\n总计: deps={ok_deps}/{len(dwd_uuids)}, outputs={ok_out}/{len(dwd_uuids)}, failed={failed}"
    )


if __name__ == "__main__":
    asyncio.run(main())

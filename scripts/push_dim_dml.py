"""把 DML 重新推到 01_DIM 目录下已建的 DIM 节点(只动 script.content, 不动调度/依赖/输出)。"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("push_dim_dml")

DIM_BASE = "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM"


def extract_dml_for_table(dml_content: str, table_name: str) -> str | None:
    pattern = rf"(insert\s+overwrite\s+table\s+\S*{re.escape(table_name)}\b.*?;)"
    match = re.search(pattern, dml_content, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


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
    dml_dir = r"E:\dw-modeling-template\sql\order-fulfillment\dim\dml"
    dml_contents: dict[str, str] = {}
    for f in Path(dml_dir).glob("*.sql"):
        dml_contents[f.stem] = f.read_text(encoding="utf-8")

    bff = DataWorksClient()
    dim_uuids = await fetch_dim_uuids(bff)
    logger.info("DIM 节点: %d", len(dim_uuids))

    ok = failed = 0
    for table_name, uuid in dim_uuids.items():
        dml = None
        for content in dml_contents.values():
            dml = extract_dml_for_table(content, table_name)
            if dml:
                break
        if not dml:
            print(f"  SKIP: {table_name} (no DML found in {dml_dir})")
            failed += 1
            continue
        success = await bff.update_node(uuid, dml)
        status = "OK" if success else "FAIL"
        print(f"  {status}: {table_name} (uuid={uuid})")
        if success:
            ok += 1
        else:
            failed += 1

    await bff.close()
    print(f"\n总计: {ok} 成功 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())

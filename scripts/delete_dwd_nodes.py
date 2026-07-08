"""删除指定路径前缀下的所有 DWD 节点。"""
from __future__ import annotations

import asyncio
import logging

from dataworks_agent.api_clients.bff_client import DataWorksClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("delete_nodes")


async def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("usage: delete_dwd_nodes.py <path_prefix>")
        sys.exit(1)

    prefix = sys.argv[1]
    bff = DataWorksClient()

    deleted = 0
    failed = 0
    page = 1
    while True:
        r = await bff._get(
            "ide/searchFiles",
            {"projectId": bff.project_id, "keyword": "dwd_ord_", "scene": "DATAWORKS_PROJECT", "pageSize": 100, "pageNum": page},
        )
        hits = (r.get("data") or {}).get("data", {}).get("hits", []) or []
        if not hits:
            break
        matched = [h for h in hits if (h.get("path") or "").startswith(prefix)]
        for h in matched:
            path = h.get("path")
            vertex_uuid = (h.get("xattrs") or {}).get("vertexProperties", {}).get("uuid")
            if not vertex_uuid:
                print(f"  SKIP: {path} (no vertex uuid)")
                continue
            resp = await bff._post(
                "ide/deletePackage",
                {"projectId": bff.project_id, "uuid": vertex_uuid},
            )
            ok = resp.get("code") == 200
            print(f"  {'OK' if ok else 'FAIL'}: {path} (uuid={vertex_uuid})")
            if ok:
                deleted += 1
            else:
                failed += 1
        page += 1
        if len(hits) < 100:
            break

    await bff.close()
    print(f"\n总计: {deleted} 删 / {failed} 失败")


if __name__ == "__main__":
    asyncio.run(main())

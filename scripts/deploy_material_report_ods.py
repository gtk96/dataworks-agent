"""Deploy ODS MC sync node for tiktok_smart_plus_material_report_hour."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.cookie.crypto import decrypt_cookie
from dataworks_agent.naming.schedule import HOURLY_SQL_PARAMETERS, generate_cron, get_cycle_type

TABLE_NAME = "ods_mc_ads_data__tiktok_smart_plus_material_report_hour"
NODE_PATH = f"dataworks_agent/01_ODS/{TABLE_NAME}"
DML_PATH = Path(
    r"E:\dw-modeling-template\sql\mkt\ods\dml\ods_mc_ads_data__tiktok_smart_plus_material_report_hour_dml.sql"
)


async def main() -> None:
    dml = DML_PATH.read_text(encoding="utf-8")
    bff = DataWorksClient()
    bff._cookie = decrypt_cookie()

    existing = await bff.get_node_list(search=TABLE_NAME, force_refresh=True)
    uid = None
    if existing:
        file_id = existing[0].get("fileId") or existing[0].get("nodeId")
        meta = await bff.get_file(f"{NODE_PATH}/.dataworks/metadata.json")
        parsed = bff.parse_ide_file(meta)
        uid = parsed.get("uuid") or str(file_id or "")
        print("existing node", uid)

    if not uid:
        uid = await bff.create_node(TABLE_NAME, NODE_PATH, language="odps-sql")
        print("create_node", uid, bff.last_error)

    if not uid:
        raise SystemExit("create_node failed")

    if not await bff.update_node(uid, dml):
        raise SystemExit(f"update_node failed: {bff.last_error}")

    cron = generate_cron("hour", minute=0)
    cycle_type = get_cycle_type("hour")
    scheduled = await bff.update_vertex(
        uid,
        {
            "trigger": {
                "type": "Scheduler",
                "cron": cron,
                "cycleType": cycle_type,
                "startTime": "1970-01-01 00:00:00",
                "endTime": "9999-01-01 00:00:00",
                "timezone": "Asia/Shanghai",
            },
            "script": {"parameters": HOURLY_SQL_PARAMETERS},
            "strategy": {"instanceMode": "Immediately"},
            "dependencies": [{"type": "CrossCycleDependsOnSelf"}],
            "outputs": {
                "nodeOutputs": [
                    {
                        "data": uid,
                        "refTableName": f"giikin.{TABLE_NAME}",
                        "artifactType": "NodeOutput",
                        "sourceType": "System",
                        "isDefault": True,
                    }
                ]
            },
        },
    )
    print("schedule", scheduled, bff.last_error)

    try:
        deployed = await bff.deploy_nodes([uid], comment=f"deploy {TABLE_NAME}")
        print("deploy", deployed, bff.last_error)
    except Exception as exc:
        print("deploy skipped/failed:", exc)
    print("node_uuid", uid)

    await bff.close()


if __name__ == "__main__":
    asyncio.run(main())

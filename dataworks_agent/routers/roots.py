"""词根校验 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dataworks_agent.modeling.root_checker import RootChecker
from dataworks_agent.schemas import RootCheckRequest

router = APIRouter()
checker = RootChecker()


@router.post("/check")
async def check_roots(body: RootCheckRequest):
    """校验字段列表的词根合规性。"""
    result = await checker.check_fields(body.fields)
    return result.model_dump()


@router.post("/check-table/{table_name}")
async def check_table_roots(table_name: str):
    """校验整张表的词根合规性。"""
    from dataworks_agent.config import settings
    from dataworks_agent.mcp.operations import get_table_ddl

    try:
        ddl = await get_table_ddl(f"odps.{settings.dataworks_dev_schema}.{table_name}")
        # 从 DDL 解析字段名
        fields = []
        for line in ddl.split("\n"):
            line = line.strip().rstrip(",")
            if "PARTITIONED BY" in line.upper():
                break
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("CREATE") and not line.startswith("("):
                fields.append(parts[0].strip('`"'))
        if not fields:
            raise HTTPException(status_code=400, detail="未能解析到字段")
        result = await checker.check_fields(fields)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验失败: {e}") from e


@router.post("/cache/refresh")
async def refresh_cache():
    """刷新词根缓存（等同 governance 同步接口）。"""
    from dataworks_agent.governance.word_root_sync import run_word_root_sync_once

    try:
        result = await run_word_root_sync_once(force=True)
        if result.get("status") == "failed":
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=result.get("detail", "词根同步失败"))
        return {"message": "词根已同步", **result}
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=str(exc)) from exc

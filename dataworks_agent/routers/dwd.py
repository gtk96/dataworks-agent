"""DWD visual modeler API — preview DDL/SQL and six-step deploy."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class StructuredMetadataPayload(BaseModel):
    structured_metadata: dict = Field(
        ..., description="Visual modeler payload (sources/targets/joins/mappings)"
    )


class DwdDeployRequest(StructuredMetadataPayload):
    node_path: str = "dataworks_agent/02_DWD"
    node_name: str | None = None
    mc_project: str = ""
    schedule_minute: int = 1
    publish: bool = True


@router.post("/preview-ddl")
async def preview_ddl(body: StructuredMetadataPayload):
    """从 structured_metadata 生成 MaxCompute CREATE TABLE DDL。"""
    from dataworks_agent.modeling.dwd import DwdDDLGenerator

    try:
        gen = DwdDDLGenerator()
        ddl_meta = gen.from_structured_metadata(body.structured_metadata)
        ddl = gen.generate(ddl_meta)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"status": "ok", "ddl": ddl, "target_table": ddl_meta.target_table_name}


@router.post("/preview-sql")
async def preview_sql(body: StructuredMetadataPayload):
    """从 structured_metadata 生成 DWD INSERT SQL（含增量 UNION ALL 模式）。"""
    from dataworks_agent.modeling.dwd import DwdSQLGenerator, build_structured_metadata

    try:
        metadata = build_structured_metadata(body.structured_metadata)
        sql = DwdSQLGenerator().generate(metadata)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "ok",
        "sql": sql,
        "target_table": metadata.target_table_name,
        "update_mode": metadata.update_mode,
    }


@router.post("/deploy")
async def deploy_dwd(body: DwdDeployRequest):
    """六步部署：DDL → 建表 → SQL → 节点 → 调度 → 发布。"""
    from dataworks_agent.modeling.dwd import DwdDeployPipeline
    from dataworks_agent.state import app_state

    bff = getattr(app_state, "_bff_client", None)
    node_client = getattr(app_state, "_node_client", None)
    mc_client = getattr(app_state, "_maxcompute_client", None)
    if not bff and not node_client:
        raise HTTPException(status_code=503, detail="节点客户端不可用")

    # 节点操作优先 AK/SK 适配器、建表优先 AK/SK MaxCompute；缺则降级 bff（Task 8a/8b）
    pipeline = DwdDeployPipeline(bff, node_client=node_client, mc_client=mc_client)
    try:
        result = await pipeline.deploy(
            body.structured_metadata,
            node_path=body.node_path,
            node_name=body.node_name,
            mc_project=body.mc_project or None,
            schedule_minute=body.schedule_minute,
            publish=body.publish,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "ok" if result["success"] else "partial",
        **result,
    }


@router.post("/resolve-types")
async def resolve_types(body: StructuredMetadataPayload):
    """批量解析目标字段类型（无 LLM，规则 + 关键词）。"""
    from dataworks_agent.modeling.dwd import DwdTypeResolver

    targets = body.structured_metadata.get("targets") or []
    if not targets:
        raise HTTPException(status_code=422, detail="targets must not be empty")

    resolver = DwdTypeResolver()
    resolved = []
    for field in targets[0].get("fields") or []:
        name = field.get("name")
        if not name:
            continue
        outcome = resolver.resolve(name, field.get("comment") or field.get("description"))
        resolved.append(
            {
                "name": name,
                "type": outcome.type,
                "category": outcome.category,
                "issues": [
                    {"severity": i.severity, "element": i.element, "description": i.description}
                    for i in outcome.issues
                ],
            }
        )

    return {"status": "ok", "fields": resolved}

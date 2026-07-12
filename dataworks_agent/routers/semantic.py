"""语义层 API — 版本化语义定义、口径澄清、质量信号。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class SemanticDefinitionRequest(BaseModel):
    """语义定义请求。"""

    kind: str = Field(..., description="类型: metric/caliber/dimension/alias/permission/root/rule")
    key: str = Field(..., description="标识")
    body: dict[str, Any] = Field(default_factory=dict, description="定义内容")
    actor: str = Field(default="", description="操作者")


class KnowledgeExtractRequest(BaseModel):
    """从 SQL 抽取待审核的知识候选。"""

    sql: str = Field(..., min_length=1)
    dialect: str = Field(default="hive")
    source: dict[str, Any] = Field(default_factory=dict)


class KnowledgeApproveRequest(BaseModel):
    """显式批准完整指标查询契约。"""

    confirmed: bool = False
    query_contract: dict[str, Any] = Field(default_factory=dict)
    actor: str = ""


class SemanticDefinitionResponse(BaseModel):
    """语义定义响应。"""

    def_id: str
    kind: str
    key: str
    body: dict[str, Any]
    version: int
    status: str


@router.get("/definitions")
async def list_definitions(
    kind: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """列出语义定义，支持搜索和分页。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()

    # 获取所有定义
    all_definitions = layer.list_definitions(kind=kind, status=status, limit=10000)

    # 搜索过滤
    if search:
        search_lower = search.lower()
        all_definitions = [
            d
            for d in all_definitions
            if search_lower in d.key.lower()
            or search_lower in d.kind.lower()
            or search_lower in str(d.body).lower()
        ]

    # 分页
    total = len(all_definitions)
    offset = (page - 1) * page_size
    paginated_definitions = all_definitions[offset : offset + page_size]

    return {
        "definitions": [
            {
                "def_id": d.def_id,
                "kind": d.kind,
                "key": d.key,
                "body": d.body,
                "version": d.version,
                "status": d.status,
                "created_by": d.created_by,
                "created_at": d.created_at,
            }
            for d in paginated_definitions
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/definitions/{def_id}")
async def get_definition(def_id: str):
    """获取语义定义。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()
    definitions = layer.list_definitions()
    definition = next((d for d in definitions if d.def_id == def_id), None)

    if not definition:
        raise HTTPException(status_code=404, detail=f"定义 {def_id} 不存在")

    return {
        "def_id": definition.def_id,
        "kind": definition.kind,
        "key": definition.key,
        "body": definition.body,
        "version": definition.version,
        "status": definition.status,
    }


@router.post("/definitions")
async def create_definition(body: SemanticDefinitionRequest):
    """创建语义定义。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()
    definition = layer.upsert_definition(
        kind=body.kind,
        key=body.key,
        body=body.body,
        actor=body.actor,
    )

    resp: dict[str, Any] = {
        "def_id": definition.def_id,
        "kind": definition.kind,
        "key": definition.key,
        "version": definition.version,
        "status": definition.status,
    }

    if definition.version > 1:
        resp["note"] = (
            f"已存在旧版，创建为 v{definition.version}（当前 status={definition.status}）"
        )

    return resp


@router.post("/definitions/{def_id}/approve")
async def approve_definition(def_id: str):
    """批准语义定义。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()
    success = layer.approve_definition(def_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"定义 {def_id} 不存在")

    return {"status": "ok", "def_id": def_id}


@router.delete("/definitions/{def_id}")
async def delete_definition(def_id: str, hard: bool = False):
    """删除语义定义（软删除，默认标记为 deleted）。

    Args:
        def_id: 定义 ID
        hard: 是否硬删除（彻底删除记录）
    """
    from datetime import datetime

    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import SemanticDefModel

    with SessionLocal() as db:
        model = db.get(SemanticDefModel, def_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"定义 {def_id} 不存在")

        if hard:
            # 硬删除
            db.delete(model)
        else:
            # 软删除：标记为 deleted
            model.status = "deleted"
            model.body_json = json.dumps(
                {
                    **json.loads(model.body_json),
                    "_deleted_at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            )

        db.commit()

    return {"status": "ok", "def_id": def_id, "deleted": "hard" if hard else "soft"}


@router.post("/definitions/{def_id}/restore")
async def restore_definition(def_id: str):
    """恢复已删除的定义。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import SemanticDefModel

    with SessionLocal() as db:
        model = db.get(SemanticDefModel, def_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"定义 {def_id} 不存在")

        if model.status != "deleted":
            raise HTTPException(status_code=400, detail=f"定义 {def_id} 未被删除")

        # 恢复为 draft 状态
        body = json.loads(model.body_json)
        body.pop("_deleted_at", None)
        model.status = "draft"
        model.body_json = json.dumps(body, ensure_ascii=False)
        db.commit()

    return {"status": "ok", "def_id": def_id}


@router.put("/definitions/{def_id}")
async def update_definition(def_id: str, body: dict[str, Any]):
    """更新语义定义。"""
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import SemanticDefModel

    with SessionLocal() as db:
        model = db.get(SemanticDefModel, def_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"定义 {def_id} 不存在")

        if "kind" in body:
            model.kind = body["kind"]
        if "key" in body:
            model.key = body["key"]
        if "body" in body:
            model.body_json = json.dumps(body["body"], ensure_ascii=False)
        if "status" in body:
            model.status = body["status"]
        if "created_by" in body:
            model.created_by = body["created_by"]

        db.commit()

    return {"status": "ok", "def_id": def_id}


@router.post("/caliber/clarify")
async def clarify_caliber(body: dict[str, Any]):
    """口径澄清。"""
    from dataworks_agent.runtime.caliber import CaliberClarificationRequest, CaliberClarifier

    metric_id = body.get("metric_id", "")
    expected_caliber = body.get("expected_caliber", "")

    clarifier = CaliberClarifier()
    request = CaliberClarificationRequest(
        metric_id=metric_id,
        expected_caliber=expected_caliber,
    )
    result = await clarifier.clarify(request)

    return {
        "metric_id": result.metric_id,
        "resolved": result.resolved,
        "caliber_match": result.caliber_match,
        "explanation": result.explanation,
        "root_cause": result.root_cause,
    }


@router.get("/quality/{table_name}")
async def get_quality_signal(table_name: str):
    """获取质量信号 — 从 DataWorks DQC 获取真实数据。"""
    from dataworks_agent.semantic.dqc_service import get_dqc_service

    dqc = get_dqc_service()

    # 构建 table_guid
    from dataworks_agent.governance.table_name_parser import build_table_guid

    try:
        table_guid = build_table_guid(table_name)
    except Exception as exc:
        logger.warning("build_table_guid 失败 (table=%s): %s", table_name, exc)
        table_guid = f"odps.dataworks.{table_name}"

    # 从 DQC 获取质量信号
    signal = await dqc.get_table_quality_signal(table_guid)

    return signal


@router.post("/bootstrap")
async def bootstrap_from_standards():
    """从 Standards_Bundle 导入语义规则。"""
    from dataworks_agent.semantic.layer import SemanticLayer

    layer = SemanticLayer()
    count = layer.bootstrap_from_standards()

    return {"status": "ok", "imported_count": count}


@router.get("/knowledge/items")
async def list_knowledge_items():
    """列出 draft 经营概念与可执行 approved 指标。"""
    from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase

    knowledge = SemanticKnowledgeBase()
    drafts = [item.to_dict() for item in knowledge.items()]
    approved = [
        {**definition, "kind": "metric", "executable": True}
        for definition in knowledge.approved_metrics()
    ]
    return {"items": drafts, "approved_metrics": approved}


@router.get("/knowledge/search")
async def search_knowledge(q: str):
    """搜索经营指标知识，并融合当前数据专辑证据。"""
    from dataworks_agent.semantic.album_context import DataAlbumContextResolver
    from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase

    resolver = DataAlbumContextResolver()
    contexts = await resolver.resolve(q)
    return SemanticKnowledgeBase().search(q, contexts).to_dict()


@router.post("/knowledge/extract")
async def extract_knowledge(body: KnowledgeExtractRequest):
    """从 SQL 提取表、聚合、CASE、过滤和维度；结果始终为 draft。"""
    from dataworks_agent.semantic.knowledge_extractor import SQLKnowledgeExtractor

    result = SQLKnowledgeExtractor().extract(
        body.sql,
        source=body.source,
        dialect=body.dialect,
    )
    if result.parse_errors and not result.candidates:
        raise HTTPException(status_code=422, detail=result.to_dict())
    return result.to_dict()


@router.post("/knowledge/candidates/{candidate_id}/approve")
async def approve_knowledge_candidate(candidate_id: str, body: KnowledgeApproveRequest):
    """仅在人工确认且 query contract 完整时批准指标。"""
    from dataworks_agent.semantic.knowledge_base import SemanticKnowledgeBase
    from dataworks_agent.semantic.layer import SemanticLayer

    if not body.confirmed:
        raise HTTPException(status_code=400, detail="必须显式 confirmed=true 才能批准指标口径")
    contract = dict(body.query_contract)
    contract.setdefault("id", candidate_id)
    if contract["id"] != candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id 与 query_contract.id 不一致")
    if not SemanticKnowledgeBase.is_executable_definition(contract):
        raise HTTPException(
            status_code=422,
            detail=(
                "query contract 不完整：必须包含 id、table、measure.column/aggregation、"
                "freshness.date_partition、asset_provenance.type/album_id"
            ),
        )
    layer = SemanticLayer()
    definition = layer.upsert_definition(
        kind="metric",
        key=candidate_id,
        body={"query_contract": contract},
        actor=body.actor,
        source="knowledge_review",
    )
    if not layer.approve_definition(definition.def_id):
        raise HTTPException(status_code=500, detail="指标口径写入成功但批准失败")
    return {
        "status": "approved",
        "def_id": definition.def_id,
        "metric_id": candidate_id,
        "version": definition.version,
        "query_contract": contract,
    }

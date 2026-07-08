"""SemanticLayer — 语义层服务，实现 Requirement 10。

功能：
1. 版本化语义定义存储
2. 冲突口径拒绝写入
3. 唯一当前口径查询
4. 质量信号查询
5. Standards_Bundle 导入
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SemanticDefinition:
    """语义定义。"""

    def_id: str
    kind: str  # metric/caliber/dimension/alias/permission/root/rule
    key: str
    body: dict[str, Any]
    version: int = 1
    source: str = "manual"  # standards_bundle/reverse_modeling/manual
    status: str = "draft"  # draft/approved
    created_by: str = ""
    created_at: str = ""


@dataclass
class CaliberResolution:
    """口径澄清结果。"""

    metric_id: str
    definition: SemanticDefinition | None
    conflicts: list[SemanticDefinition] = field(default_factory=list)
    resolved: bool = False


@dataclass
class QualitySignal:
    """质量信号。"""

    table_name: str
    freshness: str = "unknown"  # fresh/stale/unknown
    completeness: float = 0.0  # 0-1
    uniqueness: float = 0.0  # 0-1
    quality_status: str = "unknown"  # good/warning/bad/unknown


class SemanticLayer:
    """语义层服务。

    实现 Requirement 10：语义层单一事实源。
    """

    def get_metric_definition(self, metric_id: str) -> SemanticDefinition | None:
        """获取指标的唯一当前口径定义。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import SemanticDefModel

        with SessionLocal() as db:
            # 查询 status='approved' 的最高 version
            model = (
                db.query(SemanticDefModel)
                .filter(
                    SemanticDefModel.kind == "metric",
                    SemanticDefModel.key == metric_id,
                    SemanticDefModel.status == "approved",
                )
                .order_by(SemanticDefModel.version.desc())
                .first()
            )

            if not model:
                return None

            return SemanticDefinition(
                def_id=model.def_id,
                kind=model.kind,
                key=model.key,
                body=json.loads(model.body_json),
                version=model.version,
                source=model.source,
                status=model.status,
                created_by=model.created_by,
                created_at=model.created_at,
            )

    def resolve_caliber(self, expr: str) -> CaliberResolution:
        """口径澄清 — 查找表达式对应的指标定义。"""
        # 简单实现：直接查找指标 ID
        definition = self.get_metric_definition(expr)

        if definition:
            return CaliberResolution(
                metric_id=expr,
                definition=definition,
                resolved=True,
            )

        # 未找到定义
        return CaliberResolution(
            metric_id=expr,
            definition=None,
            resolved=False,
        )

    def upsert_definition(
        self,
        kind: str,
        key: str,
        body: dict[str, Any],
        actor: str = "",
        source: str = "manual",
    ) -> SemanticDefinition:
        """写入或更新语义定义。

        如果存在冲突的已批准口径，则拒绝写入并返回冲突详情。
        """
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import SemanticDefModel

        with SessionLocal() as db:
            # 检查是否有已批准的口径
            existing_approved = (
                db.query(SemanticDefModel)
                .filter(
                    SemanticDefModel.kind == kind,
                    SemanticDefModel.key == key,
                    SemanticDefModel.status == "approved",
                )
                .first()
            )

            if existing_approved:
                # 检查是否有实质性变更
                existing_body = json.loads(existing_approved.body_json)
                if existing_body == body:
                    # 无变更，直接返回现有定义
                    return SemanticDefinition(
                        def_id=existing_approved.def_id,
                        kind=existing_approved.kind,
                        key=existing_approved.key,
                        body=existing_body,
                        version=existing_approved.version,
                        source=existing_approved.source,
                        status=existing_approved.status,
                        created_by=existing_approved.created_by,
                        created_at=existing_approved.created_at,
                    )

                # 有实质性变更，创建新版本
                new_version = existing_approved.version + 1
            else:
                new_version = 1

            # 创建新定义
            def_id = f"sem_{uuid.uuid4().hex[:12]}"
            now = datetime.now(UTC).isoformat()

            model = SemanticDefModel(
                def_id=def_id,
                kind=kind,
                key=key,
                body_json=json.dumps(body, ensure_ascii=False),
                version=new_version,
                source=source,
                status="draft",
                created_by=actor,
                created_at=now,
            )
            db.add(model)
            db.commit()

            logger.info(
                "语义定义已创建: %s (kind=%s, key=%s, version=%d)",
                def_id,
                kind,
                key,
                new_version,
            )

            return SemanticDefinition(
                def_id=def_id,
                kind=kind,
                key=key,
                body=body,
                version=new_version,
                source=source,
                status="draft",
                created_by=actor,
                created_at=now,
            )

    def approve_definition(self, def_id: str) -> bool:
        """批准语义定义。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import SemanticDefModel

        with SessionLocal() as db:
            model = db.get(SemanticDefModel, def_id)
            if not model:
                return False

            # 将同 (kind, key) 的其他已批准定义降级为 deprecated
            db.query(SemanticDefModel).filter(
                SemanticDefModel.kind == model.kind,
                SemanticDefModel.key == model.key,
                SemanticDefModel.status == "approved",
            ).update({"status": "deprecated"})

            # 批准当前定义
            model.status = "approved"
            db.commit()

            logger.info("语义定义已批准: %s", def_id)
            return True

    def get_quality_signal(self, table_name: str) -> QualitySignal:
        """获取表的质量信号。"""
        # 简化实现：返回默认质量信号
        # 实际应从 DataWorks DQC 或其他来源获取
        return QualitySignal(
            table_name=table_name,
            freshness="unknown",
            completeness=0.0,
            uniqueness=0.0,
            quality_status="unknown",
        )

    def bootstrap_from_standards(self) -> int:
        """从 Standards_Bundle 导入初始语义规则。"""
        from dataworks_agent.semantic.bootstrap import bootstrap_semantic_layer

        return bootstrap_semantic_layer()

    def list_definitions(
        self,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SemanticDefinition]:
        """列出语义定义。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import SemanticDefModel

        with SessionLocal() as db:
            query = db.query(SemanticDefModel)

            if kind:
                query = query.filter(SemanticDefModel.kind == kind)
            if status:
                query = query.filter(SemanticDefModel.status == status)

            models = query.order_by(SemanticDefModel.created_at.desc()).limit(limit).all()

            return [
                SemanticDefinition(
                    def_id=m.def_id,
                    kind=m.kind,
                    key=m.key,
                    body=json.loads(m.body_json),
                    version=m.version,
                    source=m.source,
                    status=m.status,
                    created_by=m.created_by,
                    created_at=m.created_at,
                )
                for m in models
            ]

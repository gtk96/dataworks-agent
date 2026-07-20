"""学习存储 — 持久化从反思中提取的规则与策略。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class LearnedRule:
    """一条从历史案例中提炼的学习规则。"""

    rule_id: str
    rule_type: str  # planning / execution / verification
    condition: str  # 触发条件描述
    action: str  # 建议动作
    confidence: float = 0.5
    source_episode_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        now = datetime.now(UTC).isoformat()
        if self.created_at is None:
            self.created_at = datetime.fromisoformat(now)
        if self.updated_at is None:
            self.updated_at = datetime.fromisoformat(now)


class LearningStore:
    """基于 SQLite 的学习规则存储。

    Args:
        session_factory: 返回 SQLAlchemy Session 的可调用对象。
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def add_rule(self, rule: LearnedRule) -> None:
        """添加新规则或更新已有规则（按 rule_id 去重）。"""
        from dataworks_agent.db.models import LearnedRuleModel

        session = self._session_factory()
        try:
            row = session.get(LearnedRuleModel, rule.rule_id)
            if row is None:
                row = LearnedRuleModel(rule_id=rule.rule_id)

            row.rule_type = rule.rule_type
            row.condition = rule.condition
            row.action = rule.action
            row.confidence = max(0.0, min(1.0, rule.confidence))
            row.source_episode_ids_json = json.dumps(rule.source_episode_ids, ensure_ascii=False)
            row.updated_at = datetime.now(UTC).isoformat()
            if row.created_at == "":
                row.created_at = row.updated_at

            session.add(row)
            session.commit()
            logger.info(
                "Learned rule stored: %s (type=%s, confidence=%.2f)",
                rule.rule_id,
                rule.rule_type,
                rule.confidence,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def get_rules(self, rule_type: str | None = None) -> list[LearnedRule]:
        """查询学习规则，可按类型过滤。"""
        from dataworks_agent.db.models import LearnedRuleModel

        session = self._session_factory()
        try:
            stmt = select(LearnedRuleModel)
            if rule_type:
                stmt = stmt.where(LearnedRuleModel.rule_type == rule_type)
            stmt = stmt.order_by(LearnedRuleModel.confidence.desc())
            rows = session.execute(stmt).scalars().all()
            return [self._row_to_rule(row) for row in rows]
        finally:
            session.close()

    async def update_confidence(self, rule_id: str, delta: float) -> None:
        """调整规则置信度。delta 可为正（验证成功）或负（验证失败）。"""
        from dataworks_agent.db.models import LearnedRuleModel

        session = self._session_factory()
        try:
            row = session.get(LearnedRuleModel, rule_id)
            if row is None:
                logger.warning("Rule not found for confidence update: %s", rule_id)
                return

            row.confidence = max(0.0, min(1.0, row.confidence + delta))
            row.updated_at = datetime.now(UTC).isoformat()
            session.add(row)
            session.commit()
            logger.info(
                "Confidence updated for rule %s: %.3f -> %.3f",
                rule_id,
                row.confidence - delta,
                row.confidence,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def archive_low_confidence_rules(self, threshold: float = 0.3) -> int:
        """归档低置信度规则（置信度低于阈值的标记为 archived）。

        Returns:
            被归档的规则数量。

        注意：当前实现不物理删除，而是将 confidence 设为 0 并记录日志。
        后续可扩展为增加 status 字段支持软删除。
        """
        from dataworks_agent.db.models import LearnedRuleModel

        session = self._session_factory()
        try:
            stmt = (
                select(LearnedRuleModel)
                .where(LearnedRuleModel.confidence < threshold)
                .order_by(LearnedRuleModel.confidence.asc())
            )
            rows = session.execute(stmt).scalars().all()
            count = 0
            for row in rows:
                row.confidence = 0.0
                row.updated_at = datetime.now(UTC).isoformat()
                session.add(row)
                count += 1
                logger.info("Archived low-confidence rule: %s (was %.3f)", row.rule_id, threshold)

            if count > 0:
                session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def increment_success_count(self, rule_id: str) -> None:
        """规则被验证成功时提升置信度。"""
        await self.update_confidence(rule_id, 0.1)

    async def increment_failure_count(self, rule_id: str) -> None:
        """规则被验证失败时降低置信度。"""
        await self.update_confidence(rule_id, -0.15)

    def _row_to_rule(self, row: Any) -> LearnedRule:
        return LearnedRule(
            rule_id=row.rule_id,
            rule_type=row.rule_type,
            condition=row.condition,
            action=row.action,
            confidence=float(row.confidence) if row.confidence is not None else 0.5,
            source_episode_ids=json.loads(row.source_episode_ids_json or "[]"),
            created_at=datetime.fromisoformat(row.created_at)
            if row.created_at
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(row.updated_at)
            if row.updated_at
            else datetime.now(UTC),
        )

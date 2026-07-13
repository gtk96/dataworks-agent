"""RootChecker — 使用线上同步到 SQLite 的词根与内置字典校验。"""

from __future__ import annotations

import json
import logging

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import ModelingTaskModel
from dataworks_agent.schemas import RootCheckField, RootCheckResult

logger = logging.getLogger(__name__)


class RootChecker:
    """词根校验器。"""

    async def check(self, task_id: str) -> None:
        """对建模任务的目标字段执行词根校验。"""
        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task:
                raise RuntimeError(f"任务 {task_id} 不存在")
            columns = json.loads(task.columns_json) if task.columns_json else []

        if not columns:
            logger.warning("任务 %s 无字段列表，跳过词根校验", task_id)
            return

        field_names = [c.get("name", "") for c in columns if c.get("name")]
        result = await self.check_fields(field_names)

        if not result.passed:
            error_msg = f"词根校验不通过: {result.summary}"
            logger.warning("任务 %s: %s", task_id, error_msg)
            raise RuntimeError(error_msg)

        logger.info("任务 %s 词根校验通过 (%d 字段)", task_id, len(field_names))

    async def check_fields(self, fields: list[str]) -> RootCheckResult:
        """使用本地缓存校验；缓存由治理同步任务从 MaxCompute/BFF 更新。"""
        return self._check_local_fallback(fields)

    def check_fields_local(self, fields: list[str]) -> RootCheckResult:
        """仅使用内置词根字典（离线降级）。"""
        return self._check_local_fallback(fields)

    def _check_local_fallback(self, fields: list[str]) -> RootCheckResult:
        """基于线上同步缓存与内置词根字典校验各段。"""
        from dataworks_agent.standards.loader import (
            valid_root_tokens,
            validate_field_roots,
            word_root_source,
        )

        roots = valid_root_tokens()
        field_results = []
        for field_name in fields:
            illegal = validate_field_roots(field_name, roots)
            field_results.append(
                RootCheckField(
                    field_name=field_name,
                    valid=not illegal,
                    invalid_segments=illegal,
                    suggested_name=None,
                )
            )

        all_valid = all(f.valid for f in field_results)
        source = "online" if word_root_source() == "online" else "local"
        source_label = (
            "online synced root dictionary"
            if source == "online"
            else "local built-in root dictionary"
        )
        return RootCheckResult(
            passed=all_valid,
            field_results=field_results,
            summary=(
                f"{sum(1 for f in field_results if not f.valid)}/{len(fields)} invalid fields "
                f"({source_label})"
            ),
            source=source,
        )

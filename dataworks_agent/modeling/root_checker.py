"""RootChecker — 词根合规性校验，MCP check_column_roots 主力 + 备用本地降级。"""

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
        """校验字段列表的词根合规性。优先 MCP，MCP 不可用时走本地降级。"""
        try:
            return await self._check_via_mcp(fields)
        except Exception as e:
            logger.warning("MCP 词根校验不可用，降级为本地校验: %s", e)
            return self._check_local_fallback(fields)

    async def _check_via_mcp(self, fields: list[str]) -> RootCheckResult:
        """通过 MCP check_column_roots 校验。"""
        from dataworks_agent.mcp.operations import check_column_roots

        raw = await check_column_roots(",".join(fields))

        field_results = []
        for r in raw or []:
            field_results.append(
                RootCheckField(
                    field_name=r.get("column_name", ""),
                    valid=r.get("is_valid", False),
                    invalid_segments=r.get("invalid_parts", []),
                    suggested_name=r.get("suggested_name"),
                )
            )

        all_valid = all(f.valid for f in field_results)
        return RootCheckResult(
            passed=all_valid,
            field_results=field_results,
            summary=f"{sum(1 for f in field_results if not f.valid)}/{len(fields)} 个字段不合规",
        )

    def _check_local_fallback(self, fields: list[str]) -> RootCheckResult:
        """本地降级：基于内置词根字典校验各段。"""
        from dataworks_agent.standards.loader import valid_root_tokens, validate_field_roots

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
        return RootCheckResult(
            passed=all_valid,
            field_results=field_results,
            summary=f"{sum(1 for f in field_results if not f.valid)}/{len(fields)} 个字段不合规 (本地词根字典)",
        )

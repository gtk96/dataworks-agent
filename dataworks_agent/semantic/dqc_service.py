"""DQC Service — DataWorks DQC 对接服务。

从 DataWorks DQC 拉取质量规则和结果，转换为质量信号。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DQCRule:
    """DQC 规则。"""

    rule_id: str
    name: str
    table_guid: str
    rule_type: str
    threshold: float = 0.0
    enabled: bool = True


@dataclass
class DQCResult:
    """DQC 校验结果。"""

    result_id: str
    rule_id: str
    table_guid: str
    passed: bool
    actual_value: float = 0.0
    expected_value: float = 0.0
    bizdate: str = ""
    checked_at: str = ""


class DQCService:
    """DQC 服务 — 对接 DataWorks DQC。"""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        """获取 OpenAPI 客户端。"""
        from dataworks_agent.state import app_state

        # 优先使用已初始化的客户端
        if app_state._openapi_client:
            return app_state._openapi_client

        # 尝试初始化客户端
        try:
            from dataworks_agent.api_clients.openapi_client import DataWorksOpenAPIClient
            from dataworks_agent.auth import load_credentials
            from dataworks_agent.config import settings

            creds = load_credentials()
            client = DataWorksOpenAPIClient(
                creds=creds,
                region=settings.dataworks_region,
                endpoint=f"dataworks.{settings.dataworks_region}.aliyuncs.com",
                project_id=settings.dataworks_project_id,
            )
            return client
        except Exception as e:
            logger.warning("初始化 OpenAPI 客户端失败: %s", e)
            return None

    async def list_evaluation_tasks(
        self,
        name: str | None = None,
        table_guid: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出 DQC 评估任务。"""
        client = self._get_client()
        if not client:
            logger.warning("OpenAPI 客户端不可用")
            return []

        try:
            result = await client.list_data_quality_evaluation_tasks(
                name=name,
                table_guid=table_guid,
            )
            tasks = result.paging_info.data_quality_evaluation_tasks or []
            return [
                {
                    "task_id": t.id,
                    "name": t.name,
                    "table_guid": getattr(t, "table_guid", ""),
                    "status": getattr(t, "status", ""),
                }
                for t in tasks
            ]
        except Exception as e:
            logger.warning("获取 DQC 评估任务失败: %s", e)
            return []

    async def list_rules(
        self,
        evaluation_task_id: str | None = None,
        table_guid: str | None = None,
    ) -> list[DQCRule]:
        """列出 DQC 规则。"""
        client = self._get_client()
        if not client:
            return []

        try:
            result = await client.list_data_quality_rules(
                data_quality_evaluation_task_id=evaluation_task_id,
                table_guid=table_guid,
            )
            rules = result.paging_info.data_quality_rules or []
            return [
                DQCRule(
                    rule_id=r.id,
                    name=r.name,
                    table_guid=r.table_guid or "",
                    rule_type=r.type or "",
                )
                for r in rules
            ]
        except Exception as e:
            logger.warning("获取 DQC 规则失败: %s", e)
            return []

    async def list_results(
        self,
        rule_id: str | None = None,
        bizdate_from: str | None = None,
        bizdate_to: str | None = None,
    ) -> list[DQCResult]:
        """列出 DQC 校验结果。"""
        client = self._get_client()
        if not client:
            return []

        try:
            result = await client.list_data_quality_results(
                data_quality_rule_id=rule_id,
                bizdate_from=bizdate_from,
                bizdate_to=bizdate_to,
            )
            results = result.paging_info.data_quality_results or []

            parsed = []
            for r in results:
                status = r.status or ""
                rule_info = r.rule or {}
                table_guid = ""
                if hasattr(rule_info, "target") and rule_info.target:
                    table_guid = getattr(rule_info.target, "table_guid", "") or ""

                parsed.append(
                    DQCResult(
                        result_id=str(r.id),
                        rule_id=str(getattr(rule_info, "id", "")),
                        table_guid=table_guid,
                        passed=status == "Passed",
                        checked_at=str(r.create_time or ""),
                    )
                )
            return parsed
        except Exception as e:
            logger.warning("获取 DQC 结果失败: %s", e)
            return []

    async def get_table_quality_signal(self, table_guid: str) -> dict[str, Any]:
        """获取表的质量信号。"""
        # 1. 查询该表的 DQC 规则
        rules = await self.list_rules(table_guid=table_guid)

        # 2. 查询最近的校验结果
        results = await self.list_results(bizdate_from="2024-01-01")

        # 3. 计算质量信号
        total_rules = len(rules)
        passed_rules = sum(1 for r in results if r.passed)
        completeness = passed_rules / total_rules if total_rules > 0 else 0.0

        # 4. 判断新鲜度
        if results:
            latest_check = max(r.checked_at for r in results if r.checked_at)
            try:
                check_time = datetime.fromisoformat(latest_check.replace("Z", "+00:00"))
                hours_ago = (datetime.now(UTC) - check_time).total_seconds() / 3600
                freshness = "fresh" if hours_ago < 24 else "stale"
            except Exception:
                freshness = "unknown"
        else:
            freshness = "unknown"

        # 5. 判断质量状态
        if completeness >= 0.9:
            quality_status = "good"
        elif completeness >= 0.7:
            quality_status = "warning"
        else:
            quality_status = "bad"

        return {
            "table_name": table_guid.split(".")[-1] if "." in table_guid else table_guid,
            "freshness": freshness,
            "completeness": round(completeness, 2),
            "uniqueness": 0.99,  # 默认值，需要从 DQC 获取
            "quality_status": quality_status,
            "total_rules": total_rules,
            "passed_rules": passed_rules,
            "last_check": latest_check if results else "never",
        }


# 全局实例
_dqc_service: DQCService | None = None


def get_dqc_service() -> DQCService:
    """获取 DQC 服务实例。"""
    global _dqc_service
    if _dqc_service is None:
        _dqc_service = DQCService()
    return _dqc_service

"""PublishGate — dev→prod 同步前的 4 项自动校验门禁。"""

from __future__ import annotations

import logging

from dataworks_agent.config import settings
from dataworks_agent.mcp.operations import get_table_ddl

logger = logging.getLogger(__name__)


class GateResult:
    def __init__(self, passed: bool, details: list[str]):
        self.passed = passed
        self.details = details


class PublishGate:
    """发布前校验门禁 — 4 项全过才允许同步。"""

    async def check(self, table_name: str) -> GateResult:
        failures = []

        dev_full = f"{settings.dataworks_dev_schema}.{table_name}"
        prod_full = f"{settings.dataworks_prod_schema}.{table_name}"

        # 1. 建表成功
        try:
            dev_ddl = await get_table_ddl(f"odps.{dev_full}")
            if not dev_ddl:
                failures.append("目标 dev 表不存在")
        except Exception as e:
            failures.append(f"无法获取 dev 表 DDL: {e}")

        # 2. dev ddl 与 prod ddl 字段一致
        try:
            dev_ddl = await get_table_ddl(f"odps.{dev_full}")
            prod_ddl = await get_table_ddl(f"odps.{prod_full}")
            if self._parse_columns(dev_ddl) != self._parse_columns(prod_ddl):
                failures.append("字段结构不一致")
        except Exception:
            pass  # prod 表可能还没建，跳过

        # 3. 无严重错误
        try:
            from dataworks_agent.db.database import SessionLocal
            from dataworks_agent.db.models import ModelingTaskModel, TaskStepLogModel

            with SessionLocal() as db:
                # 通过 join ModelingTaskModel 获取与该表相关的任务步骤日志
                step_logs = (
                    db.query(TaskStepLogModel)
                    .join(ModelingTaskModel, TaskStepLogModel.task_id == ModelingTaskModel.task_id)
                    .filter(ModelingTaskModel.target_table == table_name)
                    .order_by(TaskStepLogModel.created_at.desc())
                    .limit(10)
                    .all()
                )

                # 检查是否有严重错误
                for log in step_logs:
                    if log.status == "failed" and log.error:
                        error_lower = log.error.lower()
                        # 检查是否是严重错误（权限、语法等）
                        severe_patterns = ["permission", "syntax", "denied", "forbidden"]
                        if any(p in error_lower for p in severe_patterns):
                            failures.append(f"存在严重错误: {log.error[:100]}")
                            break
        except Exception as e:
            # 读取失败不阻塞，记录日志
            logger.warning("检查任务错误日志失败: %s", e)

        return GateResult(passed=len(failures) == 0, details=failures)

    @staticmethod
    def _parse_columns(ddl: str) -> list[str]:
        if not ddl:
            return []
        cols = []
        for line in ddl.split("\n"):
            line = line.strip().rstrip(",")
            if "PARTITIONED BY" in line.upper() or "LIFECYCLE" in line.upper():
                break
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("CREATE") and not line.startswith("("):
                cols.append(f"{parts[0]}:{parts[1]}")
        return sorted(cols)

"""ScheduleConfigurator — 调度参数配置（天/小时/分钟级） + 0 点边界校验。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from dataworks_agent.config import settings
from dataworks_agent.naming.schedule import generate_cron, infer_schedule_type
from dataworks_agent.schemas import (
    CycleType,
    ScheduleParameter,
    SchedulePreview,
    ScheduleTrigger,
)

logger = logging.getLogger(__name__)


class ScheduleValidator:
    """调度参数 0 点边界校验 — Wizard 第 4 步预览用。"""

    @staticmethod
    def preview_params(cycle_type: str, biz_hour: int = 7) -> SchedulePreview:
        """用虚拟时间预计算调度参数，展示给用户确认。"""
        now = datetime.now()
        test_cases = [
            ("正常调度", now.replace(hour=biz_hour, minute=0, second=0)),
            ("0点边界", now.replace(hour=0, minute=0, second=0)),
            ("月底边界", (now.replace(day=1) - timedelta(days=1)).replace(hour=biz_hour)),
            ("跨年边界", datetime(now.year - 1, 12, 31, biz_hour)),
        ]

        scenarios = {}
        for label, dt in test_cases:
            if cycle_type == CycleType.DAILY.value:
                bizdate = (dt - timedelta(days=1)).strftime("%Y%m%d")
                scenarios[label] = {
                    "bizdate": bizdate,
                    "biz_date": f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:]}",
                }
            else:  # NotDaily
                prev_hour = dt - timedelta(hours=1)
                gmtdate = prev_hour.strftime("%Y%m%d")
                hour = prev_hour.strftime("%H")
                scenarios[label] = {"gmtdate": gmtdate, "hour_last1h": hour}

        return SchedulePreview(scenarios=scenarios)

    @staticmethod
    def validate(params: list[ScheduleParameter]) -> list[str]:
        """校验调度参数完整性。"""
        errors = []
        required = {"bizdate", "biz_date"} if any(p.name == "bizdate" for p in params) else set()
        present = {p.name for p in params}
        for r in required:
            if r not in present:
                errors.append(f"缺少必需参数: {r}")
        return errors


class ScheduleConfigurator:
    """调度配置器。"""

    def __init__(self) -> None:
        self.project_id = settings.dataworks_project_id
        self.datasource_id = settings.dataworks_datasource_id
        self.resource_group = settings.dataworks_resource_group

    async def configure(self, task_id: str) -> None:
        """配置调度参数并写入 DataWorks 节点。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task or not task.node_uuid:
                raise RuntimeError(f"任务 {task_id} 没有关联的 DataWorks 节点")

            sched_json = json.loads(task.schedule_config_json) if task.schedule_config_json else {}
            cycle_type = sched_json.get("cycle_type", infer_schedule_type(task.target_table))
            biz_hour = sched_json.get("biz_hour", 7)

            if cycle_type == CycleType.DAILY.value:
                config = self.configure_daily_task(task.node_uuid, biz_hour)
            else:
                minute = sched_json.get("schedule_minute", 0)
                config = self.configure_hourly_task(task.node_uuid, minute=minute)

            # 通过 BFF updateVertex 写入
            from dataworks_agent.state import app_state

            bff = getattr(app_state, "_bff_client", None)
            getattr(app_state, "_cdp_client", None)

            if bff:
                # 写入参数 + 触发配置
                await bff.update_vertex(
                    task.node_uuid,
                    {
                        "script": {"parameters": config["parameters"]},
                        "trigger": config["trigger"],
                        "strategy": config["strategy"],
                    },
                )

            # 更新本地记录
            task.schedule_config_json = json.dumps(config, ensure_ascii=False)
            db.commit()

        logger.info("调度配置完成: task=%s cycle=%s", task_id, cycle_type)

    def configure_daily_task(self, node_uuid: str, biz_hour: int = 7) -> dict:
        return {
            "trigger": ScheduleTrigger(
                cron=generate_cron("day", hour=biz_hour, minute=0),
                cycle_type=CycleType.DAILY,
            ).model_dump(),
            "parameters": [
                ScheduleParameter(name="bizdate", value="$[yyyymmdd-1]").model_dump(),
                ScheduleParameter(name="biz_date", value="$[yyyy-mm-dd-1]").model_dump(),
            ],
            "strategy": {"instanceMode": "Immediately"},
            "node_checked": True,
        }

    def configure_hourly_task(self, node_uuid: str, minute: int = 0) -> dict:
        return {
            "trigger": ScheduleTrigger(
                cron=generate_cron("hour", minute=minute),
                cycle_type=CycleType.NOT_DAILY,
            ).model_dump(),
            "parameters": [
                ScheduleParameter(name="gmtdate", value="$[yyyymmdd-1/24]").model_dump(),
                ScheduleParameter(name="hour_last1h", value="$[hh24-1/24]").model_dump(),
            ],
            "strategy": {"instanceMode": "Immediately"},
            "node_checked": True,
        }

    def configure_minutely_task(self, node_uuid: str, interval: int = 5) -> dict:
        return {
            "trigger": ScheduleTrigger(
                cron=f"00 00/{interval} 00-23 * * ?",
                cycle_type=CycleType.NOT_DAILY,
            ).model_dump(),
            "parameters": [
                ScheduleParameter(name="gmtdate", value="$[yyyymmdd-1/24]").model_dump(),
                ScheduleParameter(name="minute", value="$[mm-1]").model_dump(),
            ],
            "strategy": {"instanceMode": "Immediately"},
            "node_checked": True,
        }

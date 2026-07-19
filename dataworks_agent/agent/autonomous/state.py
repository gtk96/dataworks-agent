"""状态模型定义 — Autonomous Agent 核心数据对象。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class TaskType(StrEnum):
    """自主任务类型枚举。"""

    CREATE_ODS = "create_ods"
    CREATE_DWD = "create_dwd"
    MODIFY_TASK = "modify_task"
    CONFIGURE_SCHEDULE = "configure_schedule"
    CONFIGURE_DEPENDENCY = "configure_dependency"


class ExecutionStatus(StrEnum):
    """任务执行状态流转。"""

    PLANNED = "planned"
    EXECUTING = "executing"
    VERIFIED = "verified"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"


class StepResult(BaseModel):
    """单步执行结果。"""

    step: str = Field(description="步骤名称")
    status: str = Field(default="pending", description="步骤状态: pending/completed/failed/skipped")
    details: dict[str, Any] = Field(default_factory=dict, description="步骤详情")
    error: str | None = Field(default=None, description="错误信息")
    duration_ms: float = Field(default=0.0, description="执行耗时（毫秒）")


class AutonomousTask(BaseModel):
    """自主任务实例。"""

    model_config = ConfigDict()

    id: str = Field(default_factory=lambda: f"auto_{uuid.uuid4().hex[:12]}", description="任务 ID")
    task_type: TaskType = Field(description="任务类型")
    description: str = Field(description="任务描述")
    params: dict[str, Any] = Field(default_factory=dict, description="任务参数")
    plan: list[dict[str, Any]] = Field(default_factory=list, description="执行计划步骤")
    status: ExecutionStatus = Field(default=ExecutionStatus.PLANNED, description="执行状态")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="更新时间")
    error_message: str | None = Field(default=None, description="错误信息")
    verification_result: dict[str, Any] | None = Field(default=None, description="验证结果")
    step_results: list[StepResult] = Field(default_factory=list, description="各步骤执行结果")

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        data = self.model_dump()
        for key in ("created_at", "updated_at"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].isoformat()
        return data

    def mark_executing(self) -> None:
        self.status = ExecutionStatus.EXECUTING
        self.updated_at = datetime.now(UTC)

    def mark_verified(self) -> None:
        self.status = ExecutionStatus.VERIFIED
        self.updated_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        self.status = ExecutionStatus.FAILED
        self.error_message = error
        self.updated_at = datetime.now(UTC)

    def add_step_result(self, result: StepResult) -> None:
        self.step_results.append(result)
        self.updated_at = datetime.now(UTC)


class AutonomousContext(BaseModel):
    """自主执行上下文，约束操作边界。"""

    project_id: str = Field(description="DataWorks 项目 ID")
    business_folder: str = Field(description="业务流程文件夹路径")
    allowed_data_sources: list[str] = Field(default_factory=list, description="允许的数据源类型")
    user_id: str = Field(description="用户 ID")
    session_id: str = Field(description="会话 ID")


class VerifierResult(BaseModel):
    """验证器返回的统一结果结构。"""

    success: bool = Field(description="是否全部通过")
    checks: list[dict[str, Any]] = Field(default_factory=list, description="逐项检查结果")
    summary: str = Field(default="", description="摘要说明")
    warnings: list[str] = Field(default_factory=list, description="警告信息")

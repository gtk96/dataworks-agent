"""Pydantic 数据模型 — 所有 API 请求/响应和领域对象的共享类型定义。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from dataworks_agent.config import settings


def require_write_access(x_api_key: str = Header(default="", alias="X-API-Key")):
    """写操作鉴权依赖：检查 X-API-Key header 是否匹配配置。

    当 deploy_api_key 为空时跳过校验（兼容未配置场景）。
    """
    if settings.deploy_api_key and x_api_key != settings.deploy_api_key:
        raise HTTPException(status_code=403, detail="API Key 无效，禁止写操作")


# ═══════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DDL_GEN = "ddl_gen"
    TABLE_CRE = "table_cre"
    ROOT_CHECK = "root_check"
    DML_WRITE = "dml_write"
    SCHED_CFG = "sched_cfg"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    TIMEOUT = "timeout"


class UpdateMethod(StrEnum):
    DAY = "day"
    HOUR = "hour"
    HOURLY = "hourly"
    ALL = "all"
    STATIC = "static"


class DataLayer(StrEnum):
    ODS = "ODS"
    DWD = "DWD"
    DWS = "DWS"
    DMR = "DMR"
    DIM = "DIM"
    HOLO = "HOLO"


class CycleType(StrEnum):
    DAILY = "Daily"
    NOT_DAILY = "NotDaily"


class CookieHealth(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    EXPIRED = "expired"
    DEGRADED = "degraded"


class PermissionLevel(StrEnum):
    L0 = "L0"  # 只读
    L1 = "L1"  # 创建任务
    L2 = "L2"  # 同步生产
    L3 = "L3"  # 管理员


# ═══════════════════════════════════════════════════════════════
# 字段 & 表结构
# ═══════════════════════════════════════════════════════════════


class ColumnDef(BaseModel):
    name: str
    type: str = "string"
    comment: str = ""
    is_partition: bool = False


class TableDefinition(BaseModel):
    table_name: str
    schema_name: str
    columns: list[ColumnDef] = []
    partition_keys: list[str] = []
    layer: DataLayer = DataLayer.DWD
    ddl_text: str = ""


class TableStructure(BaseModel):
    table_name: str
    columns: list[ColumnDef] = []
    partition_keys: list[str] = []
    source_format: str = "structured"  # json | structured


class TableInfo(BaseModel):
    name: str
    schema_name: str = ""
    layer: str = ""


class DataSourceInfo(BaseModel):
    name: str
    ds_type: str
    connection_info: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════
# 调度配置
# ═══════════════════════════════════════════════════════════════


class ScheduleParameter(BaseModel):
    name: str
    type: str = "System"
    value: str
    scope: str = "NodeParameter"


class ScheduleTrigger(BaseModel):
    type: str = "Scheduler"
    cron: str = "00 00 07 * * ?"
    cycle_type: CycleType = CycleType.DAILY
    start_time: str = "1970-01-01 00:00:00"
    end_time: str = "9999-01-01 00:00:00"
    timezone: str = "Asia/Shanghai"


class ScheduleStrategy(BaseModel):
    instance_mode: str = "Immediately"


class ScheduleConfig(BaseModel):
    trigger: ScheduleTrigger = Field(default_factory=ScheduleTrigger)
    parameters: list[ScheduleParameter] = []
    strategy: ScheduleStrategy = Field(default_factory=ScheduleStrategy)
    dependencies: list[str] = []
    resource_group: str = ""
    node_checked: bool = True


class SchedulePreview(BaseModel):
    """0 点边界调度参数预览结果。"""

    scenarios: dict[str, dict[str, str]] = {}


# ═══════════════════════════════════════════════════════════════
# 建模任务
# ═══════════════════════════════════════════════════════════════


class CreateTaskRequest(BaseModel):
    source_table: str
    target_layer: DataLayer = DataLayer.DWD
    domain: str = "mkt"
    entity: str = ""
    update_method: UpdateMethod = UpdateMethod.DAY
    columns_override: list[ColumnDef] = []
    partition_keys: list[str] = []
    schedule_config: ScheduleConfig | None = None
    dry_run: bool = False
    source_datasource_name: str = ""
    dwd_metadata: dict[str, Any] | None = None


class ModelingTask(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    steps: list[dict[str, Any]] = []
    created_by_ip: str = ""
    project_id: int = 0
    source_table: str = ""
    target_table: str = ""
    target_layer: DataLayer = DataLayer.DWD
    node_type: str = ""
    domain: str = ""
    entity: str = ""
    update_method: UpdateMethod = UpdateMethod.DAY
    columns: list[ColumnDef] = []
    partition_keys: list[str] = []
    schedule_config: ScheduleConfig | None = None
    ddl_dev: str = ""
    ddl_prod: str = ""
    dml: str = ""
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""
    node_uuid: str = ""
    node_name: str = ""


class TaskStepLog(BaseModel):
    task_id: str
    step_name: str
    status: str  # intent | running | completed | failed
    intent_operation: str = ""
    intent_target: str = ""
    intent_payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    error: str = ""
    duration_ms: float = 0
    created_at: str = ""


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    target_table: str = ""
    target_layer: str = ""
    node_type: str = ""
    created_by_ip: str = ""
    created_at: str = ""
    updated_at: str = ""
    duration_seconds: float = 0


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    page: int = 1
    page_size: int = 20


class TaskDetailResponse(BaseModel):
    task: ModelingTask
    step_logs: list[TaskStepLog] = []


# ═══════════════════════════════════════════════════════════════
# 词根校验
# ═══════════════════════════════════════════════════════════════


class RootCheckField(BaseModel):
    field_name: str
    valid: bool
    invalid_segments: list[str] = []
    suggested_name: str | None = None


class RootCheckResult(BaseModel):
    passed: bool
    field_results: list[RootCheckField] = []
    summary: str = ""


class RootCheckRequest(BaseModel):
    fields: list[str]
    force_refresh: bool = False


# ═══════════════════════════════════════════════════════════════
# 同步
# ═══════════════════════════════════════════════════════════════


class SyncJob(BaseModel):
    job_id: str
    source_table: str
    target_table: str
    status: str = "pending"
    diff_report: dict[str, Any] = {}
    alter_sql: str = ""
    sync_sql: str = ""
    execution_log: str = ""
    created_by_ip: str = ""
    created_at: str = ""


class SyncDiffResponse(BaseModel):
    has_changes: bool
    diff_details: list[dict[str, Any]] = []
    alter_sql: str = ""
    requires_user_action: bool = False


class SyncExecuteRequest(BaseModel):
    table_name: str
    project_id: int = 0


# ═══════════════════════════════════════════════════════════════
# 血缘
# ═══════════════════════════════════════════════════════════════


class LineageNode(BaseModel):
    table: str
    upstream_table: str = ""
    task_id: str = ""
    task_name: str = ""


class LineageGraph(BaseModel):
    nodes: list[LineageNode] = []
    edges: list[dict[str, str]] = []
    cycles: list[list[str]] = []


# ═══════════════════════════════════════════════════════════════
# Reconciliation
# ═══════════════════════════════════════════════════════════════


class ReconciliationTask(BaseModel):
    task_id: str
    step_name: str
    intent_operation: str = ""
    intent_target: str = ""
    created_at: str = ""


class ReconciliationDisposeRequest(BaseModel):
    task_id: str
    action: Literal["retry", "confirm_success", "confirm_failed"]


# ═══════════════════════════════════════════════════════════════
# 监控 & 仪表盘
# ═══════════════════════════════════════════════════════════════


class HourlyBucket(BaseModel):
    hour: str
    completed: int = 0
    failed: int = 0


class DashboardResponse(BaseModel):
    total_tasks: int = 0
    success_rate: float = 0.0
    avg_duration_seconds: float = 0.0
    today_completed: int = 0
    today_failed: int = 0
    hourly_trend: list[HourlyBucket] = []
    layer_breakdown: dict[str, int] = {}
    queue_backlog: int = 0
    active_tasks: int = 0


# ═══════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════


class HealthChecks(BaseModel):
    bff_api: str = "unknown"
    cdp: str = "unknown"
    mcp: str = "unknown"
    cookie: str = "unknown"
    cookie_expires_in: int = 0
    cookie_health: str = "unknown"
    db: str = "unknown"


class HealthResponse(BaseModel):
    status: str = "unknown"  # ok | degraded | down
    version: str = "0.1.0"
    uptime_seconds: int = 0
    checks: HealthChecks = Field(default_factory=HealthChecks)


# ═══════════════════════════════════════════════════════════════
# Cookie
# ═══════════════════════════════════════════════════════════════


class CookieStatusResponse(BaseModel):
    valid: bool = False
    expires_in: int = 0
    health: CookieHealth = CookieHealth.EXPIRED
    username: str = ""


class CookieSaveRequest(BaseModel):
    cookie_string: str


# ═══════════════════════════════════════════════════════════════
# 产权 & 总线矩阵
# ═══════════════════════════════════════════════════════════════


class OwnershipRecord(BaseModel):
    table_name: str
    field_name: str = ""
    created_by_ip: str = ""
    last_modified_by_ip: str = ""
    business_owner: str = ""
    change_type: str = "create"
    created_at: str = ""


class BusMatrixEntry(BaseModel):
    domain: str
    dimension: str
    has_link: bool = False
    tables: list[str] = []


# ═══════════════════════════════════════════════════════════════
# 产物
# ═══════════════════════════════════════════════════════════════


class ArtifactEntry(BaseModel):
    id: int
    task_id: str
    table_name: str
    ddl_dev: str = ""
    ddl_prod: str = ""
    dml: str = ""
    schedule_config: dict[str, Any] | None = None
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════
# SSE 事件
# ═══════════════════════════════════════════════════════════════


class SSEEvent(BaseModel):
    event: str  # start | step | progress | result | error | done
    task_id: str = ""
    step: str = ""
    status: str = ""
    message: str = ""
    data: dict[str, Any] = {}
    timestamp: str = ""

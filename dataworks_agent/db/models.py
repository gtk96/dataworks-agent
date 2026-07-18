"""SQLite 数据模型 — 建模任务、步骤日志、同步作业等 ORM 映射。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dataworks_agent.db.database import Base


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ModelingTaskModel(Base):
    __tablename__ = "modeling_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_by_ip: Mapped[str] = mapped_column(String(45), default="", index=True)
    project_id: Mapped[int] = mapped_column(Integer, default=0)
    source_table: Mapped[str] = mapped_column(String(256), default="")
    target_table: Mapped[str] = mapped_column(String(256), default="")
    target_layer: Mapped[str] = mapped_column(String(10), default="DWD")
    node_type: Mapped[str] = mapped_column(String(20), default="")  # holo / odps-sql / di
    domain: Mapped[str] = mapped_column(String(64), default="")
    entity: Mapped[str] = mapped_column(String(128), default="")
    update_method: Mapped[str] = mapped_column(String(20), default="day")
    columns_json: Mapped[str] = mapped_column(Text, default="[]")
    partition_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    schedule_config_json: Mapped[str] = mapped_column(Text, default="{}")
    ddl_dev: Mapped[str] = mapped_column(Text, default="")
    ddl_prod: Mapped[str] = mapped_column(Text, default="")
    dml: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    node_uuid: Mapped[str] = mapped_column(String(64), default="")
    node_name: Mapped[str] = mapped_column(String(256), default="")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    dwd_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    # 归属（DingTalk/Web 身份解析；IP 仍保留于 created_by_ip 作回退）
    actor_team: Mapped[str] = mapped_column(String(64), default="", index=True)
    actor_org_code: Mapped[str] = mapped_column(String(64), default="", index=True)


class TaskStepLogModel(Base):
    __tablename__ = "task_step_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    step_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="intent", index=True)
    intent_operation: Mapped[str] = mapped_column(String(128), default="")
    intent_target: Mapped[str] = mapped_column(String(256), default="")
    intent_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    # Trace-Span 因果链（Event Log 升级；Requirement 29）
    span_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    parent_span_id: Mapped[str] = mapped_column(String(64), default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class TableDefinitionModel(Base):
    __tablename__ = "table_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(256), index=True)
    schema_name: Mapped[str] = mapped_column(String(64))
    layer: Mapped[str] = mapped_column(String(10))
    columns_json: Mapped[str] = mapped_column(Text, default="[]")
    ddl_text: Mapped[str] = mapped_column(Text, default="")
    created_by_ip: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class SyncJobModel(Base):
    __tablename__ = "sync_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_table: Mapped[str] = mapped_column(String(256))
    target_table: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    diff_report_json: Mapped[str] = mapped_column(Text, default="{}")
    alter_sql: Mapped[str] = mapped_column(Text, default="")
    sync_sql: Mapped[str] = mapped_column(Text, default="")
    execution_log: Mapped[str] = mapped_column(Text, default="")
    created_by_ip: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class WordRootCacheModel(Base):
    __tablename__ = "word_root_cache"

    column_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    column_desc: Mapped[str] = mapped_column(String(256), default="")
    is_digit: Mapped[int] = mapped_column(Integer, default=0)
    refreshed_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class LineageEdgeModel(Base):
    __tablename__ = "lineage_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(256), index=True)
    target_table: Mapped[str] = mapped_column(String(256), index=True)
    task_id: Mapped[str] = mapped_column(String(64), default="")
    task_name: Mapped[str] = mapped_column(String(256), default="")
    cached_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class OwnershipRecordModel(Base):
    __tablename__ = "ownership_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(256), index=True)
    field_name: Mapped[str] = mapped_column(String(128), default="")
    created_by_ip: Mapped[str] = mapped_column(String(45), default="")
    last_modified_by_ip: Mapped[str] = mapped_column(String(45), default="")
    business_owner: Mapped[str] = mapped_column(String(64), default="")
    change_type: Mapped[str] = mapped_column(String(20), default="create")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class SchemaVersionModel(Base):
    __tablename__ = "schema_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(256), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    action: Mapped[str] = mapped_column(String(20))  # CREATE | ALTER | DROP
    ddl_hash: Mapped[str] = mapped_column(String(64))
    created_by_ip: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class BusMatrixCellModel(Base):
    __tablename__ = "bus_matrix"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(64), index=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    has_link: Mapped[int] = mapped_column(Integer, default=0)
    tables_json: Mapped[str] = mapped_column(Text, default="[]")


class ReconciliationTaskModel(Base):
    __tablename__ = "reconciliation_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    step_name: Mapped[str] = mapped_column(String(64))
    intent_operation: Mapped[str] = mapped_column(String(128), default="")
    intent_target: Mapped[str] = mapped_column(String(256), default="")
    disposition: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | retry | confirmed | failed
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    table_name: Mapped[str] = mapped_column(String(256))
    ddl_dev: Mapped[str] = mapped_column(Text, default="")
    ddl_prod: Mapped[str] = mapped_column(Text, default="")
    dml: Mapped[str] = mapped_column(Text, default="")
    schedule_config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class PipelineBatchModel(Base):
    __tablename__ = "pipeline_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_ip: Mapped[str] = mapped_column(String(45), default="", index=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class PipelineTaskModel(Base):
    __tablename__ = "pipeline_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    phase: Mapped[str] = mapped_column(String(64), default="")
    phase_seq: Mapped[int] = mapped_column(Integer, default=0)
    target_table: Mapped[str] = mapped_column(String(256), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    node_uuid: Mapped[str] = mapped_column(String(64), default="")
    lease_owner: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class PipelineStepLogModel(Base):
    __tablename__ = "pipeline_step_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    step_name: Mapped[str] = mapped_column(String(64))
    step_seq: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    # Trace-Span 因果链（Event Log 升级；Requirement 29）
    span_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    parent_span_id: Mapped[str] = mapped_column(String(64), default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


# ════════════════════════════════════════════════════════════════════
# Event Log 协议对象表（Requirement 9, 24, 29）— Run / Checkpoint / Event
# ════════════════════════════════════════════════════════════════════


class RunModel(Base):
    """一次执行边界 — 承载超时/取消/成本/审批与最终结果，隶属某 Session。"""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    channel: Mapped[str] = mapped_column(String(20), default="")  # web/dingtalk/finereport/mcp
    actor_user_id: Mapped[str] = mapped_column(String(64), default="")
    actor_team: Mapped[str] = mapped_column(String(64), default="", index=True)
    actor_org_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_by_ip: Mapped[str] = mapped_column(String(45), default="")  # 身份不可解析时回退
    cost_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class CheckpointModel(Base):
    """可恢复的执行快照 — 用于中断恢复、错误回滚与重放。"""

    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    step_seq: Mapped[int] = mapped_column(Integer, default=0)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    parent_id: Mapped[int] = mapped_column(Integer, default=0)  # 0 = 无父，链式
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class EventModel(Base):
    """Event Log / Trace-Span 事实源 — 可查询、可恢复、可审计。"""

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    parent_span_id: Mapped[str] = mapped_column(String(64), default="")
    # intent/step/tool_call/llm_call/handoff/interrupt/resume/error/artifact ...
    event_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    cost_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_ms: Mapped[int] = mapped_column(Integer, default=0)
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 全局单调，支持 Last-Event-ID
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class SemanticDefModel(Base):
    """语义层单一事实源 — 版本化的指标/口径/维度/别名/权限/词根/规则定义。

    同一 (kind, key) 保留多版本历史行；当前口径 = status='approved' 的最高 version。
    """

    __tablename__ = "semantic_definitions"

    def_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # metric/caliber/dimension/alias/permission/root/rule
    kind: Mapped[str] = mapped_column(String(20), default="", index=True)
    key: Mapped[str] = mapped_column(String(256), default="", index=True)
    body_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    # standards_bundle/reverse_modeling/manual
    source: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft/approved
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class TaskMemoryModel(Base):
    """任务 Memory — Loop Engineering 的核心状态记录。

    每个任务维护一份结构化的状态记录，独立于对话上下文。
    任何 Agent 在任何时间都能读取"现在到哪儿了"。

    Validates: Requirements 38
    """

    __tablename__ = "task_memory"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # 进度追踪
    completed_steps_json: Mapped[str] = mapped_column(Text, default="[]")  # List[StepRecord]
    current_step: Mapped[str] = mapped_column(String(64), default="")

    # 决策记录
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")  # List[Decision]

    # 产物引用
    artifacts_json: Mapped[str] = mapped_column(Text, default="[]")  # List[ArtifactRef]

    # 下一步建议（供 Orchestrator 或下一轮读取）
    next_steps_json: Mapped[str] = mapped_column(Text, default="[]")  # List[NextStep]

    # 阻塞项
    blockers_json: Mapped[str] = mapped_column(Text, default="[]")  # List[Blocker]

    # 验收状态
    verification_status: Mapped[str] = mapped_column(String(20), default="pending")
    verification_json: Mapped[str] = mapped_column(Text, default="{}")  # VerificationResult

    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class BadcaseModel(Base):
    """Badcase 记录 — 评测与反馈闭环。

    Validates: Requirements 31
    """

    __tablename__ = "badcases"

    badcase_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    task_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class EvalMetricModel(Base):
    """评测指标 — 质量指标记录。

    Validates: Requirements 31
    """

    __tablename__ = "eval_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="")
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class QualitySignalModel(Base):
    """质量信号 — 数据质量记录。

    Validates: Requirements 28
    """

    __tablename__ = "quality_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(256), index=True)
    freshness: Mapped[str] = mapped_column(String(20), default="unknown")
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    uniqueness: Mapped[float] = mapped_column(Float, default=0.0)
    quality_status: Mapped[str] = mapped_column(String(20), default="unknown")
    checked_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class AnomalyReportModel(Base):
    """异常报告 — 钉钉群接入。

    Validates: Requirements 33
    """

    __tablename__ = "anomaly_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sender_name: Mapped[str] = mapped_column(String(128), default="")
    chat_id: Mapped[str] = mapped_column(String(64), default="")
    metric_id: Mapped[str] = mapped_column(String(128), default="")
    expected_value: Mapped[str] = mapped_column(String(64), default="")
    actual_value: Mapped[str] = mapped_column(String(64), default="")
    diagnosis_result: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class ConversationHistoryModel(Base):
    """对话历史持久化 — 支撑跨重启的连续对话能力。"""

    __tablename__ = "conversation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)


class UserDirectoryModel(Base):
    """用户目录 — 身份与权限。

    Validates: Requirements 34
    """

    __tablename__ = "user_directory"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), default="")
    team: Mapped[str] = mapped_column(String(64), default="", index=True)
    org_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    source: Mapped[str] = mapped_column(String(20), default="")  # dingtalk/web/ip
    created_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_utc_now)

"""数据源抽象层 — 统一 OSS / Hologres / MySQL/PG 等数据源的建模接口。

所有数据源的 ODS 入仓、DWD 明细建模、DIM 维度建模、DWS 汇总建模
均通过此层的统一接口驱动，后端 pipeline 按需分发到具体实现。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── 枚举 ──────────────────────────────────────────────────────────

class DataSourceType(str, Enum):
    """支持的数据源类型。"""

    OSS = "oss"
    HOLO = "hologres"
    MYSQL = "mysql"
    POLARDB = "polardb"
    POSTGRES = "postgresql"
    UNKNOWN = "unknown"


class FileFormat(str, Enum):
    """OSS 文件存储格式。"""

    JSON = "json"
    CSV = "csv"
    PARQUET = "parquet"
    ORC = "orc"
    AVRO = "avro"
    TEXT = "text"


class SyncMode(str, Enum):
    """关系型数据源同步模式。"""

    FULL = "full"
    INCREMENTAL = "incremental"


# ── 数据结构 ──────────────────────────────────────────────────────

class FieldMeta(BaseModel):
    """字段元数据。"""

    name: str
    data_type: str
    comment: str = ""
    is_nullable: bool = True
    is_primary_key: bool = False
    is_partition: bool = False


class SourceSchema(BaseModel):
    """源表完整元数据。"""

    source_type: DataSourceType
    project: str = ""
    database: str = ""
    schema_name: str = ""
    table_name: str
    columns: list[FieldMeta] = Field(default_factory=list)
    partition_columns: list[str] = Field(default_factory=lambda: ["dt"])
    total_rows: int | None = None
    file_format: str | None = None  # OSS 专用
    location: str | None = None  # OSS 专用
    metadata_source: str = ""  # 来源说明


class DataSourceConfig(BaseModel):
    """
    统一数据源配置 — 前端只需填写可见字段，密码等敏感信息从 .env 读取。
    """

    # ── 通用 ──
    type: DataSourceType
    name: str = ""  # DataWorks 数据源别名

    # ── OSS 特有 ──
    oss_path: str | None = None
    file_format: FileFormat = FileFormat.JSON
    wildcard: str = ""
    ingestion_mode: str = "structured"  # structured | raw_json_text

    # ── Holo 特有 ──
    holo_schema: str | None = None
    holo_table: str | None = None

    # ── MySQL/PG/Polardb 特有 ──
    database: str | None = None
    table_name: str | None = None
    jdbc_url: str | None = None  # 通常从 DataWorks 数据源获取，不直接传
    incremental_column: str | None = None  # 增量同步字段
    incremental_value: str | None = None  # 上次同步值

    # ── 通用 ──
    source_partition_value: str | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            v = v or f"{cls.__name__.lower()}_{id(cls)}"
        return v.strip()

    def is_oss(self) -> bool:
        return self.type == DataSourceType.OSS

    def is_holo(self) -> bool:
        return self.type == DataSourceType.HOLO

    def is_relational(self) -> bool:
        return self.type in (
            DataSourceType.MYSQL,
            DataSourceType.POLARDB,
            DataSourceType.POSTGRES,
        )

    def validate(self) -> list[str]:
        """校验配置完整性，返回错误列表（空 = 通过）。"""
        errors: list[str] = []

        if self.type == DataSourceType.OSS:
            if not self.oss_path:
                errors.append("OSS 数据源必须提供 oss_path")
            if not self.file_format:
                errors.append("OSS 数据源必须指定 file_format")

        elif self.type == DataSourceType.HOLO:
            if not self.holo_schema:
                errors.append("Holo 数据源必须提供 holo_schema")
            if not self.holo_table:
                errors.append("Holo 数据源必须提供 holo_table")

        elif self.type.is_relational():
            if not self.database:
                errors.append(f"{self.type.value} 数据源必须提供 database")
            if not self.table_name:
                errors.append(f"{self.type.value} 数据源必须提供 table_name")
            if self.extra_params.get("sync_mode") == SyncMode.INCREMENTAL and not self.incremental_column:
                errors.append("增量同步必须指定 incremental_column")

        return errors


# ── 目标表配置 ────────────────────────────────────────────────────

class TargetLayer(str, Enum):
    """数据仓库分层。"""

    ODS = "ods"
    DWD = "dwd"
    DIM = "dim"
    DWS = "dws"
    ADS = "ads"


class TargetConfig(BaseModel):
    """目标表配置 — 描述建模产物的分层、域、实体等信息。"""

    target_table: str
    target_layer: TargetLayer = TargetLayer.ODS
    domain: str = ""  # 业务域，如 trade / user / marketing
    entity: str = ""  # 业务实体，如 order / user / product
    description: str = ""
    partition_keys: list[str] = Field(default_factory=lambda: ["dt"])
    schedule_cycle: str = "day"  # day | hour | minute
    schedule_minute: int | None = None
    logical_primary_keys: list[str] = Field(default_factory=list)
    prod_schema: str = ""
    custom_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_table")
    @classmethod
    def _validate_table_name(cls, v: str) -> str:
        v = v.strip().lower()
        # 确保符合 ODS/DWD/DIM/DWS 前缀规范
        prefix_map = {
            TargetLayer.ODS: "ods_",
            TargetLayer.DWD: "dwd_",
            TargetLayer.DIM: "dim_",
            TargetLayer.DWS: "dws_",
            TargetLayer.ADS: "ads_",
        }
        expected_prefix = prefix_map.get(TargetLayer(v), "")
        if expected_prefix and not v.startswith(expected_prefix):
            v = expected_prefix + v.lstrip(expected_prefix)
        # 仅保留字母、数字、下划线
        v = re.sub(r"[^a-z0-9_]", "_", v)
        return v


# ── 解析器 ─────────────────────────────────────────────────────────

class DataSourceResolver:
    """
    根据 DataSourceConfig 解析源表元数据。

    不同数据源类型调用不同的后端 pipeline 来获取元数据：
    - OSS → OssImportPipeline._resolve_external_table
    - Holo → HoloOdsPipeline + load_holo_ods_columns
    - MySQL/PG → DI 节点元数据查询
    """

    def __init__(self, bff_client: Any | None = None, mcp_pool: Any | None = None) -> None:
        self._bff = bff_client
        self._mcp = mcp_pool

    async def resolve(self, config: DataSourceConfig) -> SourceSchema:
        """
        解析源表完整元数据。

        返回 SourceSchema，包含表名、字段列表、分区信息等。
        """
        if config.type == DataSourceType.OSS:
            return await self._resolve_oss(config)
        elif config.type == DataSourceType.HOLO:
            return await self._resolve_holo(config)
        elif config.type.is_relational():
            return await self._resolve_relational(config)
        else:
            raise ValueError(f"不支持的数据源类型: {config.type}")

    async def _resolve_oss(self, config: DataSourceConfig) -> SourceSchema:
        """解析 OSS 外部表元数据。"""
        from dataworks_agent.services.ods_oss.managed_discovery import (
            discover_managed_oss_schema,
        )
        from dataworks_agent.services.ods_oss.external_table import (
            ExternalTableSpec,
            build_external_table_ddl,
            source_name_from_location,
        )
        from dataworks_agent.services.ods_oss.config import parse_oss_path

        location = parse_oss_path(config.oss_path or "")
        source_name = source_name_from_location(location)

        # 尝试复用已有的 managed OSS 表
        if self._bff:
            managed = await discover_managed_oss_schema(
                self._bff,
                config.oss_path or "",
                config.file_format.value if isinstance(config.file_format, FileFormat) else config.file_format,
                include_registration=True,
            )
            if isinstance(managed, dict) and managed.get("success"):
                columns = [
                    FieldMeta(
                        name=c["name"],
                        data_type=c["type"],
                        comment=c.get("comment", ""),
                    )
                    for c in (managed.get("columns") or [{"name": "json_data", "type": "STRING"}])
                ]
                return SourceSchema(
                    source_type=DataSourceType.OSS,
                    project=managed.get("project", "giikin_develop"),
                    table_name=managed.get("table_name", source_name),
                    columns=columns,
                    partition_columns=[managed.get("partition_columns", ["pt"])[0]],
                    file_format=managed.get("file_format", config.file_format.value),
                    location=managed.get("location", str(location.get("location_uri", ""))),
                    metadata_source=managed.get("metadata_source", "dataworks_managed_datasource"),
                )

        # 新建外部表
        columns = [FieldMeta(name="json_data", data_type="STRING")]
        partition_col = config.source_partition_value or "pt"
        ext_spec = ExternalTableSpec(
            project="giikin_develop",
            table=source_name,
            columns=tuple((c.name, c.data_type) for c in columns),
            partition_columns=(partition_col,),
            file_format=config.file_format.value if isinstance(config.file_format, FileFormat) else config.file_format,
            location=str(location.get("location_uri", "")),
        )
        return SourceSchema(
            source_type=DataSourceType.OSS,
            project="giikin_develop",
            table_name=source_name,
            columns=columns,
            partition_columns=[partition_col],
            file_format=ext_spec.file_format,
            location=ext_spec.location,
            metadata_source="created_external_table",
        )

    async def _resolve_holo(self, config: DataSourceConfig) -> SourceSchema:
        """解析 Hologres 表元数据。"""
        from dataworks_agent.services.ods_holo.column_resolver import load_holo_ods_columns

        if not self._bff or not self._mcp:
            return SourceSchema(
                source_type=DataSourceType.HOLO,
                table_name=config.holo_table or "",
                schema_name=config.holo_schema or "",
                columns=[],
                metadata_source="offline",
            )

        resolved = await load_holo_ods_columns(
            self._bff, self._mcp, config.holo_schema or "", config.holo_table or "", "hour"
        )
        columns = [
            FieldMeta(
                name=c.get("name", c.get("column_name", "")),
                data_type=c.get("type", c.get("data_type", "")),
                comment=c.get("comment", ""),
                is_nullable=c.get("is_nullable", True),
            )
            for c in (resolved.get("source_columns") or [])
        ]
        return SourceSchema(
            source_type=DataSourceType.HOLO,
            schema_name=config.holo_schema or "",
            table_name=config.holo_table or "",
            columns=columns,
            metadata_source=resolved.get("metadata_source", "holo_schema"),
        )

    async def _resolve_relational(self, config: DataSourceConfig) -> SourceSchema:
        """解析关系型数据源（MySQL/PG/Polardb）元数据。"""
        # 通过 DataWorks 数据源 API 获取元数据
        if not self._bff:
            return SourceSchema(
                source_type=config.type,
                database=config.database or "",
                table_name=config.table_name or "",
                columns=[],
                metadata_source="offline",
            )

        try:
            # 尝试通过 BFF 获取表结构
            ds_name = config.name or config.database or ""
            tables_resp = await self._bff.list_datasource_tables(ds_name) if hasattr(self._bff, "list_datasource_tables") else {}
            columns = []

            # 尝试通过 JDBC 查询表结构（如果 MCP 池可用）
            if self._mcp and hasattr(self._mcp, "query_table_columns"):
                cols = await self._mcp.query_table_columns(
                    datasource_name=ds_name,
                    database=config.database or "",
                    table_name=config.table_name or "",
                )
                if cols:
                    columns = [
                        FieldMeta(
                            name=c.get("name", ""),
                            data_type=c.get("type", ""),
                            comment=c.get("comment", ""),
                            is_nullable=c.get("nullable", True),
                            is_primary_key=c.get("is_primary", False),
                        )
                        for c in cols
                    ]

            return SourceSchema(
                source_type=config.type,
                database=config.database or "",
                table_name=config.table_name or "",
                columns=columns,
                metadata_source="jdbc_metadata" if columns else "offline",
            )
        except Exception:
            # 降级：返回空结构，等待用户补充
            return SourceSchema(
                source_type=config.type,
                database=config.database or "",
                table_name=config.table_name or "",
                columns=[],
                metadata_source="offline",
            )

    async def discover_schema(self, config: DataSourceConfig) -> list[FieldMeta]:
        """
        自动发现源表字段。

        便捷方法，等价于 resolve().columns。
        """
        schema = await self.resolve(config)
        return schema.columns


def infer_data_source_type(text: str) -> DataSourceType:
    """
    从用户输入文本中推断数据源类型。

    优先级：
    1. 显式声明: "oss://..." / "holo.xxx" / "mysql数据源xxx"
    2. 协议前缀: oss:// / jdbc:mysql://
    3. 关键词匹配
    """
    text_lower = text.lower().strip()

    # OSS
    if any(kw in text_lower for kw in ["oss://", "oss_path", "对象存储", ".json", ".csv", ".parquet", ".orc"]):
        return DataSourceType.OSS

    # Hologres
    if any(kw in text_lower for kw in ["holo", "hologres", "holo_schema"]):
        return DataSourceType.HOLO

    # MySQL/PG
    if any(kw in text_lower for kw in ["mysql", "polardb", "postgres", "关系型", "jdbc:mysql", "jdbc:postgresql"]):
        for dt in (DataSourceType.MYSQL, DataSourceType.POLARDB, DataSourceType.POSTGRES):
            if dt.value in text_lower:
                return dt
        return DataSourceType.MYSQL  # 默认

    return DataSourceType.UNKNOWN


def build_datasource_config_from_text(text: str, existing: DataSourceConfig | None = None) -> DataSourceConfig:
    """
    从用户输入文本构建 DataSourceConfig。

    用于意图解析后快速构造数据源配置。
    """
    ds_type = infer_data_source_type(text)
    config = existing or DataSourceConfig(type=ds_type)

    # OSS path 提取
    oss_match = re.search(r"(oss://[^\s,，；;]+)", text)
    if oss_match:
        config.oss_path = oss_match.group(1)
        config.type = DataSourceType.OSS

    # Holo schema/table 提取
    holo_schema_match = re.search(r"holo[_\s]?schema[_\s]*[:：]\s*([a-zA-Z0-9_]+)", text)
    if holo_schema_match:
        config.holo_schema = holo_schema_match.group(1)
        config.type = DataSourceType.HOLO

    holo_table_match = re.search(r"holo[_\s]?table[_\s]*[:：]\s*([a-zA-Z0-9_]+)", text)
    if holo_table_match:
        config.holo_table = holo_table_match.group(1)
        config.type = DataSourceType.HOLO

    # Database/table 提取 (MySQL/PG)
    db_match = re.search(r"(?:database|库|db)[_\s]*[:：]\s*([a-zA-Z0-9_]+)", text)
    if db_match:
        config.database = db_match.group(1)

    tbl_match = re.search(r"(?:table|表|tbl)[_\s]*[:：]\s*([a-zA-Z0-9_]+)", text)
    if tbl_match:
        config.table_name = tbl_match.group(1)

    # File format
    fmt_match = re.search(r"(json|csv|parquet|orc|avro|text)", text.lower())
    if fmt_match and config.type == DataSourceType.OSS:
        fmt_val = fmt_match.group(1).lower()
        # Map to FileFormat enum
        format_map = {
            "json": FileFormat.JSON,
            "csv": FileFormat.CSV,
            "parquet": FileFormat.PARQUET,
            "orc": FileFormat.ORC,
            "avro": FileFormat.AVRO,
            "text": FileFormat.TEXT,
        }
        config.file_format = format_map.get(fmt_val, FileFormat.JSON)

    return config

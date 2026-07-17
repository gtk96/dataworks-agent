"""配置管理 — pydantic-settings 从 .env 加载全部配置（ADR-008）。"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """dataworks-agent 全局配置。"""

    # ── 阿里云 AK/SK 鉴权 ──
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""

    # ── DataWorks 项目 ──
    # 注意：以下 ID 都是租户级内部标识符，禁止在仓库里写具体值。
    # 本地部署请把真实值填入 .env（参考 .env.example）。
    dataworks_project_id: int = 0
    dataworks_datasource_id: int = 0
    dataworks_resource_group: str = ""
    dataworks_region: str = "cn-shenzhen"
    dataworks_tenant_id: str = ""

    # ── 数仓 Schema ──
    dataworks_dev_schema: str = "dataworks_dev"
    dataworks_prod_schema: str = "dataworks"
    odps_datasource_name: str = "dataworks"
    ddl_registry_project: str = "dataworks"
    di_resource_group: str = ""
    init_di_max_wait_seconds: int = 3600
    sql_template_root: str = "E:/dw-modeling-template/sql"
    # 导入 SQL 的可信根目录白名单；为空时回退到 sql_template_root。
    # 用于阻止 /api/import、/api/preview、/api/deploy 的路径遍历（B1）。
    import_allowed_roots: list[str] = []

    # ── MaxCompute（pyodps）执行底座 ──
    maxcompute_endpoint: str = "http://service.cn-shenzhen.maxcompute.aliyun.com/api"
    maxcompute_project: str = ""

    # ── LLM 服务（OpenAI 兼容网关，provider 无关） ──
    llm_base_url: str = "https://opencode.ai/zen/v1"
    llm_model: str = "deepseek-v4-flash-free"
    llm_api_key: str = ""
    # 分级路由可选档位；留空则回退到 llm_model（Requirement 7.4）
    llm_model_light: str = ""
    llm_model_normal: str = ""
    llm_model_complex: str = ""

    # ── Holo ──
    holo_native_schemas: str = "ofc,oms,gimp,gorder,adapi_online,cda"
    holo_instance_datasource: str = "cda_giiktok_hologres"
    holo_node_datasource: str = (
        "dataworks_holo"  # 建 Holo 数据开发节点时的 datasource 名（真机核实）
    )
    holo_ods_node_path: str = "业务流程/100_订单信息/Hologres/数据开发/00_ODS"

    # ── 服务 ──
    dw_modeling_port: int = 8085
    dw_modeling_host: str = "127.0.0.1"
    host: str = "127.0.0.1"
    port: int = 8085
    deploy_api_key: str = ""  # 写操作校验，为空时不校验
    # 受信反向代理对端 IP（如 nginx 127.0.0.1 / 10.0.0.1）；仅这些 peer 才解析 X-Forwarded-For
    trusted_proxies: list[str] = []

    # ── IDE ──
    ide_agent_dir: str = "dataworks_agent"
    root_check_node_uuid: str = ""
    dataworks_default_root_node_uuid: str = ""
    smoke_test_node_uuid: str = ""

    # ── DataWorks BFF ──
    bff_base_url: str = "https://bff-cn-shenzhen.data.aliyun.com"

    # ── Cookie 鉴权 ──
    cookie_encryption_key: str = ""

    @field_validator("cookie_encryption_key")
    @classmethod
    def _cookie_encryption_key_min_length(cls, v: str) -> str:
        """v10 §6.1：禁止空密钥派生 Fernet（OWASP 弱密钥风险）。"""
        if len(v) < 16:
            raise ValueError("COOKIE_ENCRYPTION_KEY 未设置或长度不足 16 字符，请在 .env 中配置")
        return v

    cookie_keepalive_enabled: bool = False
    cdp_url: str = "http://localhost:9222"
    auto_login_enabled: bool = True
    cookie_refresh_poll_seconds: int = 600

    # 词根表自动同步（生产 dim_pub_column_dictionary_static → 本地 SQLite）
    word_root_auto_sync_enabled: bool = True
    word_root_sync_interval_seconds: int = 7200

    @property
    def cookie_refresh_configured(self) -> bool:
        return bool((self.cdp_url or "").strip())

    # ── 告警配置 ──
    dingtalk_webhook: str = ""  # 钉钉机器人 Webhook URL
    alert_enabled: bool = True  # 是否启用告警

    # Product profile: expose only Agent-first core by default; L1-L5 semantic/runtime/MCP skeleton routes are opt-in.
    enable_experimental_platform_routes: bool = False

    # 阿里云官方 DataWorks MCP（stdio 子进程）
    official_dataworks_mcp_enabled: bool = True
    official_dataworks_mcp_command: str = "npx"
    official_dataworks_mcp_package: str = "alibabacloud-dataworks-mcp-server@1.0.45"
    official_dataworks_mcp_tool_categories: str = ""
    official_dataworks_mcp_tool_names: str = ""

    # 自主问数默认返回行数与超时限制
    ask_data_default_limit: int = 100
    ask_data_timeout_seconds: int = 120
    # 数据专辑关键字缓存（秒）：命中 BFF album list 不必每次都重拉
    ask_data_album_cache_seconds: float = 600.0

    # Derived properties
    @property
    def dataworks_endpoint(self) -> str:
        return f"dataworks.{self.dataworks_region}.aliyuncs.com"

    @property
    def db_path(self) -> str:
        return str(Path(__file__).parent.parent / "data" / "dw_modeling.db")

    @property
    def data_dir(self) -> str:
        return str(Path(__file__).parent.parent / "data")

    @property
    def log_dir(self) -> str:
        return str(Path(__file__).parent.parent / "log")

    @property
    def archive_dir(self) -> str:
        return str(Path(__file__).parent.parent / "data" / "sql_archive")

    @property
    def frontend_dir(self) -> str:
        return str(Path(__file__).parent.parent / "frontend" / "dist")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

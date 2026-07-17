# 任务目标：多数据源全链路建模 + 前端全面优化

## 一、需求概述

### 核心目标
实现 **OSS 数据源**、**Hologres 数据源**、**关系型数据库（MySQL/Polardb/Postgres 等）** 三种数据源的**对话式全链路建模**，包括：
- 数据入仓（ODS 层）
- 明细建模（DWD 层）
- 汇总建模（DWS 层）
- 维度建模（DIM 层）
- 调度配置（Cron / 依赖）
- 词根校验（列名合规）
- 发布上线

### 前端目标
全面优化前端页面，使其达到 **Codex/ChatGPT** 级别的交互体验：
- 现代化暗色主题
- 流式响应（SSE）
- Markdown/代码块渲染
- 移动端自适应
- 多数据源选择引导
- 建模进度可视化

---

## 二、后端架构设计

### 2.1 数据源抽象层

**新增文件**: `dataworks_agent/modeling/data_source.py`

定义统一的数据源接口，屏蔽 OSS/Holo/MySQL 差异：

```python
class DataSourceType(str, Enum):
    OSS = "oss"
    HOLO = "hologres"
    MYSQL = "mysql"
    POLARDB = "polardb"
    POSTGRES = "postgresql"

class DataSourceConfig(BaseModel):
    type: DataSourceType
    name: str  # DataWorks 数据源名称
    # OSS 特有
    oss_path: str | None = None
    file_format: str = "json"  # json/csv/parquet/orc
    wildcard: str = ""
    # Holo 特有
    holo_schema: str | None = None
    holo_table: str | None = None
    # MySQL/PG 特有
    jdbc_url: str | None = None
    database: str | None = None
    username: str | None = None  # 从 .env 读取，不传前端
    # 通用
    partition_columns: list[str] = ["dt"]
    source_partition_value: str | None = None

class DataSourceResolver:
    """根据 DataSourceConfig 解析源表元数据（表结构、字段、分区等）"""
    
    async def resolve(self, config: DataSourceConfig) -> SourceSchema:
        """返回源表的完整元数据"""
        ...
    
    async def discover_schema(self, config: DataSourceConfig) -> list[FieldMeta]:
        """自动发现源表字段（不同数据源策略不同）"""
        ...
```

### 2.2 全链路建模引擎升级

**修改文件**: `dataworks_agent/modeling/engine.py`

在现有 `ModelingEngine` 基础上扩展 `AnyDataSourceEngine`：

```python
class AnyDataSourceEngine:
    """支持任意数据源的全链路建模引擎"""
    
    async def build_full_pipeline(
        self,
        source_config: DataSourceConfig,
        target_config: TargetConfig,  # 包含 domain, entity, layers 等
    ) -> FullPipelinePlan:
        """
        生成完整的建模计划：
        1. ODS 层：根据数据源类型调用对应 pipeline
           - OSS → OssImportPipeline
           - Holo → HoloOdsPipeline
           - MySQL/PG → DI 节点 (DataX)
        2. DWD 层：标准明细建模
        3. DIM 层：维度表建模
        4. DWS 层：汇总建模
        5. ADS 层：应用层（可选）
        6. 调度配置：Cron + 依赖链
        7. 词根校验：列名合规检查
        """
        ...
```

### 2.3 MySQL/PG 数据源 ODS 管道

**新增文件**: `dataworks_agent/services/ods_relational/pipeline.py`

类似现有的 `OssImportPipeline` 和 `HoloOdsPipeline`，但针对 MySQL/Polardb/PostgreSQL：

```python
class RelationalOdsPipeline:
    """
    MySQL/PostgreSQL/Polardb → MaxCompute ODS
    
    实现方式：
    1. 创建 DI（数据集成）节点，使用 DataX 同步
    2. 自动推断字段类型（通过 JDBC 元数据查询）
    3. 支持全量/增量同步（基于时间戳或自增 ID）
    4. 自动配置调度依赖
    """
    
    async def run(
        self,
        datasource_name: str,
        database: str,
        table: str,
        target_table: str,
        incremental_column: str | None = None,
        incremental_value: str | None = None,
        schedule_type: str = "day",
        ...
    ) -> dict[str, Any]:
        ...
```

### 2.4 意图解析增强

**修改文件**: `dataworks_agent/agent/nlu/intent_parser.py` + `templates.py`

新增意图模板，支持多数据源识别：

```python
# templates.py 新增
"any_ods_modeling": {
    "patterns": [
        # OSS
        r"(oss|对象存储|\.json|\.csv|\.parquet).*?(ods|入仓|贴源)",
        r"oss_path.*?ods",
        # Holo
        r"(holo|hologres|实时).*?(ods|入仓)",
        r"holo_schema.*?ods",
        # MySQL/PG
        r"(mysql|polardb|postgres|关系型|jdbc).*?(ods|入仓)",
        r"数据源.*?表.*?ods",
        # 通用
        r"(全链路|端到端|完整链路).*?(ods|dwd|dws)",
        r"(建|搭|创建|搭建).*?(ods.*?dwd|ods.*?dws|ods.*?dim)",
    ],
    "required_params": [],
    "optional_params": [
        "source_type", "datasource_name", "oss_path", "holo_schema",
        "database", "table_name", "target_table", "domain", "entity",
        "layers", "schedule_cycle", "file_format", "ingestion_mode",
    ],
}
```

### 2.5 词根校验服务

**新增文件**: `dataworks_agent/governance/word_root_validator.py`

```python
class WordRootValidator:
    """
    校验 DWD/DIM/DWS 表的列名是否符合词根规范。
    
    流程：
    1. 从本地 SQLite 词根缓存加载合法词根
    2. 对生成的 DDL 列名逐一校验
    3. 标记不合规列名，给出修正建议
    4. 返回校验报告（通过/警告/失败）
    """
    
    async def validate_columns(
        self,
        table_name: str,
        columns: list[ColumnDef],
    ) -> ColumnValidationReport:
        ...
    
    async def suggest_fixes(
        self,
        invalid_column: str,
    ) -> list[str]:
        """根据词根库给出修正建议"""
        ...
```

### 2.6 调度配置服务

**新增文件**: `dataworks_agent/modeling/schedule_planner.py`

```python
class SchedulePlanner:
    """
    自动生成调度配置：
    1. Cron 表达式（天/小时/分钟级）
    2. 节点间依赖链（ODS→DWD→DIM→DWS→ADS）
    3. 资源组分配
    4. 重试策略
    5. 补数据配置
    """
    
    async def plan_dependencies(
        self,
        layers: list[str],  # ["ods", "dwd", "dim", "dws"]
        table_map: dict[str, TableInfo],
    ) -> DependencyChain:
        ...
    
    async def generate_cron(
        self,
        granularity: str,  # "day" | "hour" | "minute"
        minute_slot: int | None = None,
    ) -> str:
        ...
```

### 2.7 Agent 工作流路由

**修改文件**: `dataworks_agent/agent/workflow_service.py`

在现有 `AgentWorkflowService.execute()` 中增加 `any_ods_modeling` 意图的路由：

```python
async def execute(self, ..., action: str, params: dict) -> WorkflowResult:
    if action == "any_ods_modeling":
        return await self._execute_any_ods_modeling(params)
    
    async def _execute_any_ods_modeling(self, params: dict) -> WorkflowResult:
        """
        多数据源全链路建模工作流：
        
        步骤：
        1. 解析数据源类型（OSS/Holo/MySQL）
        2. 确认源表元数据
        3. 生成 ODS 节点（调用对应 pipeline）
        4. 生成 DWD 节点（标准建模）
        5. 生成 DIM 节点（如有维度表）
        6. 生成 DWS 节点（汇总）
        7. 配置调度 + 依赖
        8. 词根校验
        9. 生成发布计划
        """
        ...
```

---

## 三、前端架构设计

### 3.1 首页重构 — 智能对话 + 数据源引导

**新增文件**: `frontend/src/pages/SmartChatPage.vue`

取代现有的 `AgentChatPage.vue`，核心改进：

```
┌─────────────────────────────────────────────────────┐
│  DataWorks Agent  │  🟢 服务正常  │  🔄 刷新        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  👋 你好，我是 DataWorks Agent               │    │
│  │  我可以帮你完成数仓建模、数据查询、异常排查   │    │
│  │                                             │    │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │    │
│  │  │ 📦 OSS  │ │ 🗄️ Holo │ │ 🗃️ MySQL │       │    │
│  │  │ 数据入仓│ │ 数据入仓│ │ 数据入仓│       │    │
│  │  └─────────┘ └─────────┘ └─────────┘       │    │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │    │
│  │  │ 🔍 智能 │ │ 🛠️ 异  │ │ 💬 对  │       │    │
│  │  │  问数   │ │  排排查 │ │  话咨询 │       │    │
│  │  └─────────┘ └─────────┘ └─────────┘       │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │ [输入框] 描述你想做什么...         [发送 ➤] │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**核心特性**：
- 数据源类型选择卡片（OSS/Holo/MySQL），点击后自动填充 context
- SSE 流式响应，实时显示思考过程
- 代码块高亮 + Markdown 渲染
- 会话历史侧边栏
- 快捷操作面板

### 3.2 建模进度可视化

**新增文件**: `frontend/src/components/modeling/ProgressTracker.vue`

```
┌──────────────────────────────────────────────┐
│  📊 建模进度                                  │
├──────────────────────────────────────────────┤
│  ✅ ODS 层 — oss_order_detail (已创建)       │
│  ✅ DWD 层 — dwd_order_detail (已创建)       │
│  ⏳ DIM 层 — dim_user (规划中...)            │
│  ⬜ DWS 层 — dws_order_summary               │
│  ⬜ 调度配置                                 │
│  ⬜ 词根校验                                 │
│                                              │
│  进度: 2/6 完成 (33%)                        │
│  [查看产物] [继续执行] [暂停]                │
└──────────────────────────────────────────────┘
```

### 3.3 数据源管理页升级

**修改文件**: `frontend/src/pages/DataSourceManager.vue`

- 统一暗色主题
- 数据源连接测试
- 源表浏览器（树形结构）
- 一键创建 ODS 节点

### 3.4 新增页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 智能建模 | `/modeling` | 全链路建模向导（数据源选择→目标表→调度配置） |
| 任务详情 | `/tasks/:id` | 已有的 TaskDetail 升级，增加进度可视化 |
| 数据源管理 | `/datasources` | 已有，暗色主题升级 |
| 异常排查 | `/anomaly` | 已有的 AnomalyDetection 升级 |

### 3.5 组件库

**新增组件**：
- `frontend/src/components/modeling/DataSourceSelector.vue` — 数据源类型选择器
- `frontend/src/components/modeling/ModelingWizard.vue` — 建模向导
- `frontend/src/components/modeling/ProgressTracker.vue` — 进度追踪
- `frontend/src/components/modeling/DependencyGraph.vue` — 依赖关系图
- `frontend/src/components/modeling/WordRootReport.vue` — 词根校验报告

---

## 四、实施计划

### Phase 1: 后端基础（2-3天）

#### 1.1 数据源抽象层
- [ ] 创建 `data_source.py` — 统一数据源接口
- [ ] 创建 `DataSourceResolver` — 元数据解析
- [ ] 扩展现有 `OssImportPipeline` / `HoloOdsPipeline` 支持新接口

#### 1.2 MySQL/PG 数据源管道
- [ ] 创建 `ods_relational/pipeline.py`
- [ ] 实现 JDBC 元数据查询（通过 DataWorks 数据源 API）
- [ ] 实现 DataX DI 节点创建
- [ ] 支持全量/增量同步模式

#### 1.3 词根校验服务
- [ ] 创建 `word_root_validator.py`
- [ ] 集成现有 `word_root_sync.py` 缓存
- [ ] 实现列名校验 + 修正建议

#### 1.4 调度配置服务
- [ ] 创建 `schedule_planner.py`
- [ ] 实现依赖链自动生成
- [ ] 实现 Cron 表达式生成

### Phase 2: Agent 工作流集成（2天）

#### 2.1 意图解析增强
- [ ] 更新 `templates.py` 新增意图模板
- [ ] 更新 `intent_parser.py` 支持多数据源识别
- [ ] 更新 `entity_extractor.py` 提取数据源相关实体

#### 2.2 工作流路由
- [ ] 更新 `workflow_service.py` 增加 `any_ods_modeling` 路由
- [ ] 实现 `_execute_any_ods_modeling` 完整工作流
- [ ] 集成词根校验到工作流
- [ ] 集成调度配置到工作流

#### 2.3 API 端点
- [ ] 新增 `/api/modeling/pipeline` — 全链路建模 API
- [ ] 新增 `/api/modeling/validate-word-roots` — 词根校验 API
- [ ] 新增 `/api/modeling/schedule-plan` — 调度配置 API
- [ ] 新增 `/api/modeling/dependency-graph` — 依赖关系图 API

### Phase 3: 前端全面优化（3-4天）

#### 3.1 首页重构
- [ ] 创建 `SmartChatPage.vue`
- [ ] 数据源选择卡片
- [ ] SSE 流式响应
- [ ] Markdown/代码块渲染
- [ ] 会话历史管理

#### 3.2 建模组件
- [ ] `DataSourceSelector.vue`
- [ ] `ModelingWizard.vue`
- [ ] `ProgressTracker.vue`
- [ ] `DependencyGraph.vue`
- [ ] `WordRootReport.vue`

#### 3.3 页面升级
- [ ] `DataSourceManager.vue` 暗色主题
- [ ] `AnomalyDetection.vue` 暗色主题
- [ ] `TaskDetail.vue` 增加进度可视化
- [ ] 新增 `ModelingPage.vue`（全链路建模向导）

#### 3.4 响应式适配
- [ ] 移动端侧边栏折叠
- [ ] 表格横向滚动
- [ ] 弹窗/对话框移动端适配

### Phase 4: 集成测试（1-2天）

- [ ] OSS 数据源全链路建模测试
- [ ] Holo 数据源全链路建模测试
- [ ] MySQL 数据源全链路建模测试
- [ ] 词根校验功能测试
- [ ] 调度配置功能测试
- [ ] 前端交互测试
- [ ] 移动端适配测试

---

## 五、关键技术细节

### 5.1 数据源识别优先级

```
用户输入 → 意图解析 → 数据源识别：
1. 显式声明: "oss://..." / "holo_schema.xxx" / "mysql数据源xxx"
2. 表名前缀: "ods_oss_*" → OSS, "ods_holo_*" → Holo, "ods_mysql_*" → MySQL
3. 上下文推断: 从对话历史中继承
4. 默认策略: 询问用户
```

### 5.2 全链路建模流程图

```
用户: "帮我搭建从 OSS 订单数据到 DWS 汇总的全链路"
  ↓
Agent 识别意图: any_ods_modeling
  ↓
1. 解析数据源: OSS, path=oss://bucket/orders/, format=json
2. 确认目标: domain=trade, entity=order, layers=[ods,dwd,dim,dws]
3. 执行 ODS: OssImportPipeline → 创建 ods_order
4. 执行 DWD: 标准建模 → 创建 dwd_order_detail
5. 执行 DIM: 维度推导 → 创建 dim_user, dim_product
6. 执行 DWS: 汇总建模 → 创建 dws_order_summary
7. 调度配置: Cron + 依赖链
8. 词根校验: 列名合规检查
9. 输出: 完整计划 + 产物预览
```

### 5.3 词根校验规则

```python
# 校验规则：
# 1. 列名必须在 dim_pub_column_dictionary_static 中存在
# 2. 或使用标准词根组合（如 user_id = user + id）
# 3. 或使用通用后缀（如 dt, hr, pt）
# 4. 或使用数字后缀（如 col_1, col_2）

# 校验报告格式：
{
    "table": "dwd_order_detail",
    "total_columns": 15,
    "passed": 12,
    "warnings": 2,
    "failures": 1,
    "details": [
        {"column": "order_id", "status": "passed", "root": "order_id"},
        {"column": "user_name", "status": "passed", "root": "user_name"},
        {"column": "xyz_custom_field", "status": "warning", "suggestion": "建议使用标准词根"},
        {"column": "invalid_col!!!", "status": "failure", "suggestion": "列名不合规，建议使用字母+数字组合"},
    ]
}
```

### 5.4 调度配置规则

```python
# 调度依赖链：
# ODS (day) → DWD (day, depends on ODS) → DIM (day, depends on ODS)
# → DWS (day, depends on DWD + DIM) → ADS (day, depends on DWS)

# Cron 分配策略：
# - 天级: 按任务数量自动分配分钟槽位（避免并发冲突）
# - 小时级: 按任务数量自动分配分钟槽位
# - 分钟级: 用户自定义

# 依赖链格式：
{
    "ods_order": {"cron": "0 0 * * *", "depends_on": ["root_node"]},
    "dwd_order_detail": {"cron": "0 30 * * *", "depends_on": ["ods_order"]},
    "dim_user": {"cron": "0 30 * * *", "depends_on": ["ods_order"]},
    "dws_order_summary": {"cron": "0 60 * * *", "depends_on": ["dwd_order_detail", "dim_user"]},
}
```

---

## 六、非功能性需求

### 6.1 性能
- 前端首屏加载 < 2s
- SSE 响应延迟 < 500ms
- 建模任务创建 < 30s
- 词根校验 < 1s

### 6.2 安全性
- 数据源密码不经过前端
- AK/SK 仅在服务端使用
- 所有写操作经过 Publish Gate
- 词根校验结果不暴露敏感信息

### 6.3 可扩展性
- 数据源类型可插件化扩展
- 意图模板可动态加载
- 前端组件可独立升级

---

## 七、文件清单

### 新增文件
```
dataworks_agent/
├── modeling/
│   ├── data_source.py          # 数据源抽象层
│   ├── schedule_planner.py     # 调度配置服务
│   └── any_source_engine.py    # 多数据源建模引擎
├── services/
│   └── ods_relational/
│       ├── __init__.py
│       ├── pipeline.py         # MySQL/PG ODS 管道
│       └── metadata.py         # JDBC 元数据查询
├── governance/
│   └── word_root_validator.py  # 词根校验服务
└── routers/
    └── any_modeling.py         # 全链路建模 API

frontend/src/
├── pages/
│   ├── SmartChatPage.vue       # 智能对话首页
│   ├── ModelingPage.vue        # 全链路建模向导
│   └── DataSourceManager.vue   # 升级版（已有）
├── components/
│   └── modeling/
│       ├── DataSourceSelector.vue
│       ├── ModelingWizard.vue
│       ├── ProgressTracker.vue
│       ├── DependencyGraph.vue
│       └── WordRootReport.vue
└── utils/
    └── modeling-api.ts         # 建模 API 封装
```

### 修改文件
```
dataworks_agent/
├── agent/
│   ├── nlu/
│   │   ├── templates.py        # 新增意图模板
│   │   ├── intent_parser.py    # 多数据源识别
│   │   └── entity_extractor.py # 数据源实体提取
│   └── workflow_service.py     # 新增 any_ods_modeling 路由
├── config.py                   # 新增数据源配置项
└── main.py                     # 注册新路由

frontend/src/
├── pages/AgentChatPage.vue     # 替换为 SmartChatPage
├── router/index.ts             # 新增路由
├── styles/variables.css        # 暗色主题微调
└── layouts/MainLayout.vue      # 导航菜单更新
```

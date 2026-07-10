# dataworks-agent

> 智能数仓建模系统 — DataWorks 全流程自动化 (v0.1.1)

把 DataWorks 上的数仓建模工作(ODS/DWD/DWS/DIM/DMR 各层)从"手工建表 + 手工配调度 + 手工 SQL 推送"自动化,前端可视化操作,后端调 BFF + MCP + CDP 完成。

## 技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite + Pydantic + httpx + structlog (Python 3.12+)
- **前端**: Vue 3 + Vite + Element Plus + Vue Router (TypeScript)
- **外部依赖**: DataWorks BFF API + MCP (Model Context Protocol) + Chrome DevTools Protocol (CDP) + Playwright
- **浏览器自动化**: Chrome `--remote-debugging-port=9222` 用于登录态保持与 Cookie 提取

## 快速启动

### 前置

- Python ≥ 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 18
- Chrome 浏览器
- 可访问 DataWorks 工作空间(阿里云账号 + Cookie)

### 启动后端

```bash
# Windows: 一键启动(端口清理 + Chrome + uvicorn)
start.bat

# 或手动启动
uv run python -m dataworks_agent.main
```

服务监听 `http://localhost:8085`,启动时自动执行冒烟检查(MCP / BFF / CDP / Cookie / DB)。

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认 `http://localhost:5173`,通过 Vite proxy 把 `/api/*` 转发到后端 8085。

## 目录结构

```
dataworks_agent/             # 后端 (FastAPI)
├── api_clients/             # DataWorks BFF + CDP 客户端
├── cookie/                  # Cookie 加密 + 健康监测
├── db/                      # SQLite + 任务模型 + 备份
├── governance/              # DDL 检查 / 血缘 / 词根 / 更新模式推断
├── mcp/                     # MCP 客户端池 + DataWorks 操作
├── middleware/              # 限流/熔断/幂等中间件(框架,未激活)
├── modeling/                # 建模引擎 (DDL/DML/调度/血缘)
│   └── dwd/                 # DWD 专属生成器
├── naming/                  # 表名/路径/调度参数常量
├── routers/                 # REST API 路由 (19 个模块)
├── services/                # ODS 各种来源 (DI/Holo/OSS/Realtime)
├── scripts/                 # 离线运维 CLI 工具 (deploy_ods / repush_ods_dml / verify_ods_params)
├── standards/               # 数仓标准 (yaml 规范 + 词根)
├── task_engine/             # 任务状态机 + 持久化队列
└── warehouse/               # 各层 yaml 规范

frontend/                    # 前端 (Vue 3 + Vite)
├── src/pages/               # 18 个页面
├── src/router/              # 路由
├── src/components/          # 公共组件(目前 1 个,RepositoryPathPicker)
├── src/utils/               # 工具函数 (request / sse)
├── e2e/                     # Playwright E2E 测试 + fake BFF server
└── playwright.config.ts     # Playwright 配置

scripts/                     # 顶层离线运维脚本
├── deploy_dwd.py            # 批量部署 DWD 节点
├── deploy_dim.py            # 批量部署 DIM 节点(日全量)
├── push_*.py                # 增量推送(DML/依赖/参数)
├── delete_*_nodes.py        # 节点删除
└── rebuild_dwd_root.py      # DWD 根节点重建

# 注意: deploy_ods / repush_ods_dml / verify_ods_params 已挪进 dataworks_agent/scripts/ 包内
# 运行方式: `uv run python -m dataworks_agent.scripts.<name>`

tests/                       # 单元 / 集成 / 冒烟
├── unit/                    # 23 个单元测试文件, ~1800 行, 238 个 test
├── integration/             # 60 个集成测试 + conftest mock fixture
└── smoke/                   # 5 场景发布前冒烟
```

## 已实现的核心能力(7 大闭环)

### 1. ODS 数据集成(4 源)
- **DI**(向导模式):`services/ods_di/` — 解析源表 + 推断 WHERE 条件 + 创建 DI 节点
- **Hologres**:`services/ods_holo/` — IMPORT FOREIGN SCHEMA 同步
- **OSS**:`services/ods_oss/` — OSS 文件导入
- **Realtime**:`services/ods_realtime/` — Binlog → Delta → ODS

### 2. DWD 可视化建模 + 自动化部署
- 前端 `ModelingWorkbench.vue` 5 步向导 + `DwdWorkbench.vue` JSON 模式
- 后端 `modeling/engine.py:_run_dwd_pipeline()` 六步部署:DDL → 建表 → SQL → 节点 → 调度 → 发布

### 3. DIM 日全量推送
- `scripts/deploy_dim.py` 一次跑完 3 张表
- 调度参数: `DAILY_SQL_PARAMETERS`(1 个 `bizdate`)
- 自依赖: `CrossCycleDependsOnSelf`

### 4. SQL 导入 + 字段映射推断
- `ImportSql.vue` 选择 SQL 目录 → 自动解析 DDL → 推断字段类型 → 一键建表
- `modeling/field_mapper.py:infer_column_type()` 规则推断(amt→decimal, cnt→bigint, id→string)

### 5. 治理工具链
- **DDL 规范检查**: `governance/ddl_checker.py` — 命名/语法/LIFECYCLE/类型/分区
- **SQL 血缘解析**: `governance/sql_lineage.py` — sqlglot 解析 source_tables + JOIN
- **上游追溯 + 血缘导出**: `governance/lineage_service.py` — BFS 上游 + ZIP 打包
- **下游影响**: `routers/lineage.py:/downstream` — 基于 BFF dma/listLineage 双向 DAG
- **词根校验**: `modeling/root_checker.py` — MCP 优先,本地词根字典回退
- **表名解析 / 更新模式推断 / 仓库标准**: 7 个治理模块全在生产路径

### 6. 任务编排 + 持久化队列
- 状态机(`task_engine/state_machine.py`): 7 步 pending→completed + cancel/suspend/resume + 指数退避重试
- 持久化队列(`task_engine/persistent_queue.py`): SQLite + lease/claim 心跳
- 意图日志(`task_engine/intent_logger.py`): 防进程崩溃后 BFF 操作证据丢失
- SSE 实时进度流(前端 `sse.ts`)

### 7. 运维自维护
- **Cookie 健康保活**: `cookie/health.py` 5min 心跳 + WARN/CRITICAL 阈值
- **DB 备份**: `db/backup.py` 1h 全量 + 关键事件触发增量
- **启动冒烟**: `bootstrap.py` 覆盖 MCP/BFF/CDP/Cookie/DB
- **BFF 客户端**: `bff_client.py:735` 行,作为 Cookie 链路的长期兜底保留(无 AK/SK 等价的能力按 Capability Matrix 仍在调用)
- **MCP 客户端池**: `mcp/pool.py` Streamable HTTP + JSON-RPC

### 8. 语义层与 Agent 平台 (L0-L5)
- **语义层**: `semantic/layer.py` — 版本化语义定义、口径澄清、质量信号
- **语义图谱**: `semantic/graph.py` — 融合血缘+语义+元数据+质量信号
- **Agent Runtime**: `runtime/service.py` — 无状态执行、检查点、重放续跑
- **MCP Server**: `mcp_server/server.py` — 六类工具、鉴权+审计
- **正向建模**: `runtime/forward_flow.py` — NL→DDL/DML/调度→校验→审批→执行
- **逆向建模**: `runtime/reverse_flow.py` — 存量表→结构+血缘+语义候选
- **指标归因**: `runtime/attribution.py` — 口径澄清→血缘下钻→根因分类
- **自愈流程**: `runtime/self_heal.py` — 调度失败/数据异常诊断+修复提议
- **评测闭环**: `runtime/evaluator.py` — 质量指标+Badcase沉淀+反馈迭代

### 9. Agent 对话助手

#### 对话式操作

通过自然语言与数仓助手交互，支持：

- **创建表**: "创建ods_user表"
- **查询血缘**: "查询ods_user的血缘"
- **检查状态**: "检查任务状态"
- **部署节点**: "部署ods_user节点"

#### 核心模块

| 模块 | 位置 | 说明 |
|------|------|------|
| NLU 解析 | `agent/nlu/` | 意图识别 + 实体抽取 + 模板匹配 |
| 任务规划 | `agent/planner/` | 任务分解 + 依赖排序 |
| 工具执行 | `agent/executor/` | 调度 MCP/BFF/OpenAPI 完成操作 |
| 核心编排 | `agent/core.py` | 对话管理 + 上下文维护 |

#### API 接口

- `POST /api/runtime/chat` — 聊天接口（文本输入 → Agent 响应）
- `WS /api/runtime/ws` — WebSocket 实时通信（流式输出）

#### 使用示例

```bash
# 通过 API 发送指令
curl -X POST http://localhost:8085/api/runtime/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "创建ods_user表", "session_id": "test-001"}'
```

#### 前端对话组件

- `AgentChat.vue` — 主对话窗口（消息列表 + 输入框）
- `ChatMessage.vue` — 单条消息渲染（支持 Markdown）
- `QuickActions.vue` — 快捷操作按钮

## 推送脚本(SOP)

### ODS
```bash
uv run python -m dataworks_agent.scripts.deploy_ods         # 一次性部署
uv run python -m dataworks_agent.scripts.repush_ods_dml     # 重推 DML + 调度参数
uv run python -m dataworks_agent.scripts.repush_ods_dml --dry-run  # 仅解析/抽取,不动线上
uv run python -m dataworks_agent.scripts.verify_ods_params  # 线上 vs 本地 DML 字节级 diff + 语义校验
```

### DWD
```bash
uv run python scripts/deploy_dwd.py        # 一次性部署
uv run python scripts/push_dwd.py          # 重推 DML
uv run python scripts/push_dwd_deps.py     # 重推依赖
uv run python scripts/push_dwd_params.py   # 重推调度参数
uv run python scripts/rebuild_dwd_root.py  # 重建根节点
```

### DIM(日全量)
```bash
uv run python scripts/deploy_dim.py        # 一次性部署
uv run python scripts/push_dim_dml.py      # 重推 DML
uv run python scripts/push_dim_deps.py     # 重推依赖
uv run python scripts/push_dim_params.py   # 重推调度参数
```

### 删除节点
```bash
uv run python scripts/delete_dwd_nodes.py "业务流程/100_订单信息/MaxCompute/数据开发/02_DWD/"
uv run python scripts/delete_dim_nodes.py "业务流程/100_订单信息/MaxCompute/数据开发/01_DIM/"
```

## 前端页面(18 个)

| 路径 | 页面 | 用途 |
|---|---|---|
| `/` | ModelingDashboard | 首页仪表盘,任务统计/趋势/分布 |
| `/tasks` | TaskList | 任务列表,筛选/重试 |
| `/tasks/create` | ModelingWorkbench | 5 步建模向导(DWD 主力) |
| `/tasks/:id` | TaskDetail | 任务详情 + SSE 实时进度 |
| `/sync` | SyncManager | dev/prod 双环境差异对比与同步 |
| `/reconciliation` | ReconciliationView | 协调处置(dangling intents) |
| `/ownership` | OwnershipView | 产权查询 |
| `/bus-matrix` | BusMatrixView | 总线矩阵可视化 |
| `/artifacts` | ArtifactsView | DDL 产物归档 |
| `/di` | DataIntegration | ODS 数据集成(15 个 API,最复杂) |
| `/datasources` | DataSourceManager | 数据源管理 |
| `/pipeline` | PipelineHub | 持久化管道队列 |
| `/governance` | GovernanceHub | 治理工具(4 Tab) |
| `/import` | ImportSql | SQL 文件批量导入 |
| `/dwd` | DwdWorkbench | DWD JSON 模式建模 |
| `/settings` | Settings | Cookie + 服务状态 |
| `/semantic` | SemanticHub | 语义层管理 |
| `/tasks/create-wizard` | TaskCreateWizard | 任务创建向导 |

## 后端路由(19 个模块)

| 前缀 | 模块 | 端点数 |
|---|---|---|
| `/api/modeling` | 建模任务 CRUD + SSE | 7 |
| `/api/dwd` | DWD 可视化建模 | 4 |
| `/api/pipeline` | 持久化管道队列 | 5 |
| `/api/deploy` | 批量部署 | 1 |
| `/api/governance` | 治理(词根/规范/表名/血缘/标准) | 18 |
| `/api/sync` | 双环境同步 | 4 |
| `/api/cookie` | Cookie 管理 | 8 |
| `/api/lineage` | 血缘追踪(upstream/downstream/graph) | 3 |
| `/api/import` | SQL 导入 | 3 |
| `/api/roots` | 词根校验 | 3 |
| `/api/ownership` | 产权查询 | 1 |
| `/api/bus-matrix` | 总线矩阵 | 1 |
| `/api/artifacts` | 产物 | 2 |
| `/api/monitor` | 监控(任务列表 + dashboard + WebSocket) | 3 |
| `/api/logs` | 任务日志 | 1 |
| `/api/system` | 系统(health/settings) | 3 |
| `/api/semantic` | 语义层(定义/口径/质量) | 7 |
| `/api/runtime` | Runtime(会话/运行/Agent) | 10 |
| `/api/mcp-server` | MCP Server(工具调用) | 4 |
| `/api/workspace` | 数据源与工作空间 | 12 |
| `/api/reconciliation` | 协调 | 2 |
| `/api/schedule` | 调度配置 | 8 |

## 配置

通过 `.env` 注入 `dataworks_agent/config.py:Settings`:
- `DATAWORKS_PROJECT_ID` — 工作空间 ID
- `DATAWORKS_BFF_BASE_URL` — BFF 网关地址
- `COOKIE_*` — Cookie 加密密钥
- `MCP_*` — MCP server URL
- `GIRO_BOT_*` — 通知机器人(可选)

## 测试

**总计 806 个测试**(单元 691 + 集成 100 + E2E 15),多种测试分工互补:

| 类别 | 工具 | 数量 | 跑速 | 覆盖 | 跑命令 |
|---|---|---|---|---|---|
| 后端单元 | pytest | 691 | ~15s | 纯函数 / 类 / 业务逻辑(不连外部) | `uv run pytest tests/unit/` |
| 后端集成 | pytest + httpx ASGITransport | 100 | ~18s | 路由 + 中间件 + 53 个端点(全 mock) | `uv run pytest tests/integration/` |
| 前端单元 | Vitest | 13 | ~1s | 组件逻辑 / 工具函数 | `cd frontend && npm run test:unit` |
| E2E | Playwright + Chromium | 15 | ~30s | 15 个页面的真用户路径 | `cd frontend && npm run test:e2e` |

### 集成测试 (`tests/integration/`)

- `conftest.py` — 通用 `mocked_client` fixture:ASGI 内存级调用 + mock mcp_pool / bff_client / cookie / keepalive + 临时 sqlite
- 15 个测试文件覆盖所有页面
- 跑前会跳过 lifespan 和 frontend StaticFiles mount,避免 SPA 干扰

### E2E 测试 (`frontend/e2e/`)

- `fake-server.mjs` — 纯 Node 0 依赖 mock BFF,接 `:8085` 返回固定 JSON
- `playwright.config.ts` — webServer 模式自动起 vite + fake server
- 15 个 spec 覆盖 15 个关键用户路径
- 失败用例自动保留 trace + video + screenshot(`test-results/`)
- 跑前确保 `:8085` 和 `:3000` 端口空闲(fake server 在 `reuseExistingServer: true` 下会复用旧进程导致缓存)

### 调试技巧

```bash
# 集成:只跑某个页面
uv run pytest tests/integration/test_governance_hub_api.py -v

# E2E:看某个 spec 的 trace
cd frontend && npx playwright test governance.spec.ts
npx playwright show-trace test-results/governance-*/trace.zip

# 集成 fixture 自测(验证 mock 框架)
uv run pytest tests/integration/test_mocked_fixture.py -v
```

## 数据库

- 位置: `data/dw_modeling.db`(SQLite)
- 备份: `data/dw_modeling.db.bak`(定时)+ `.bak` 增量文件
- 主要表: `modeling_tasks`(建模任务)、`artifacts`(DDL/DML 产物)、`task_step_logs`(步骤日志)、`pipeline_batches`(管道批次)

## 已知限制

当前已**完全可生产**的能力如上"7 大闭环"所述。**已识别但未实现**的能力:

- 上述"7 大闭环"对应核心数仓建模链路已生产化；§8 语义层与 Agent Runtime(L0-L5)当前为骨架级实现，框架/状态机/路由就位但端到端闭环未完整覆盖，不宜与建模闭环同等视作生产就绪。
- 任务自动监控报警(无失败通知)
- 血缘预存 + 增量计算(`lineage_edges` 表为空,血缘全是实时算)
- 中间件(`middleware/`)已实现并注册 4 个:限流/幂等/IP 隔离/熔断;1 个未注册:权限
- 发布门控第 3 项检查(无严重错误)未实现
- 产权追踪(`modeling/ownership.py`)已在 `modeling/engine.py` 和 `main.py` 中调用
- 前端 TypeScript 类型体系不完整(各页面多用 `any`)

## 贡献

- 阅读 `CLAUDE.md` 了解项目工作约束
- 新增功能遵循现有分层:`routers/` 暴露 API → `modeling/` 或 `services/` 业务 → `api_clients/` 调外部
- 单元测试与实现放在 `tests/unit/test_<module>.py`

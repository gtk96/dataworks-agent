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

## 自主问数语义闭环

业务问数不再在 `workflow_service.py` 里按问句硬编码 SQL，而是按下列链路生成和验证查询：

```text
自然语言 -> DataWorks 数据专辑选表 -> approved 语义指标 -> 真实 DDL 校验 -> 只读 SQL -> AK/SK / Cookie 查询
```

- `dataworks_agent/semantic/metrics.json` 是可版本化的 baseline，`SemanticLayer` 中更高版本的 approved 定义优先。
- 数据专辑负责缩小业务域和候选表；approved 指标定义负责官方表、measure、dimension、filter 和 freshness 口径。
- 若专辑命中业务域但未收录认证表，Agent 会如实展示该差异，只有 approved 指标定义且真实 DDL 校验通过才继续执行。DDL 不可读、字段不一致或总计结果不唯一时仍会阻止执行。
- 未认证指标可使用数据专辑元数据约束 LLM 规划；无 LLM 时返回候选表和口径澄清，不报为系统故障。

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

### 8. Semantic / Runtime platform (L0-L5, hidden by default)

These modules remain in the repo as future-capability skeletons, but they are not exposed in the default product profile. The default user path is the Agent-first ODS+DWD conversational loop.

- Backend: set `ENABLE_EXPERIMENTAL_PLATFORM_ROUTES=true` to mount `/api/semantic`, `/api/runtime`, and `/api/mcp-server`.
- Frontend: set `VITE_ENABLE_ADVANCED_TOOLS=true` to show the optional backstage tools menu and routes.

Skeleton modules: `semantic/layer.py`, `semantic/graph.py`, `runtime/service.py`, `mcp_server/server.py`, `runtime/forward_flow.py`, `runtime/reverse_flow.py`, `runtime/attribution.py`, `runtime/self_heal.py`, `runtime/evaluator.py`.
### 9. Agent Chat Assistant

#### Current capability boundary

The local Agent now has a closed loop for natural-language input -> NLU intent/entity parsing -> task planning -> dry-run/proposal tool execution -> status feedback. It is designed to turn DataWorks modeling, lineage, and status requests into auditable plans and draft artifacts. The chat path must not pretend that online writes or publishes have already happened.

Current execution boundary:

- **Supported**: recognize table creation, lineage query, status check, end-to-end DataWorks workflow, and conversational ODS+DWD modeling intents; extract target table, layer, schedule, source type, datasource, ODS/DWD table, OSS path, and granularity entities; generate task plans, ODS route plans, DWD DDL/SQL previews, dependency drafts, task status, and recommended next actions.
- **Safety**: `agent/executor/tool_executor.py` only runs in dry-run/proposal mode. Real online writes such as publish, delete, overwrite, or DataWorks node creation must still use the existing modeling flow, destructive-operation guard, and Publish Gate.
- **Capability split**: AK/SK and Cookie BFF fallback coexist according to the Capability Matrix. The chat Agent can suggest the route, but it does not remove or bypass the Cookie fallback path.

#### Supported examples

- **Create table draft**: `create ods_user table`
- **Lineage query plan**: `query ods_user lineage` or `query ods_user`
- **Status check**: `check task status`
- **Complex planning**: `create ods_user table and configure schedule`
- **ODS+DWD proposal**: `build hourly ODS from mysql datasource jky_singleshop orders, then create dwd_trade_order_detail`
- **ODS route coverage**: batch DB (`ods_di`), Hologres (`ods_holo`), OSS (`ods_oss`), realtime/CDC (`ods_realtime`), and existing ODS tables all stop at dry-run/proposal plus Publish Gate boundary.

#### Core modules

| Module | Path | Description |
|------|------|------|
| NLU parsing | `agent/nlu/` | Intent recognition, entity extraction, template and fallback matching |
| Task planning | `agent/planner/` | Task decomposition, dependency ordering, safe dry-run workflow |
| Tool execution | `agent/executor/` | Draft artifacts, validate guardrails, recommend next actions; no direct online write |
| Execution monitor | `agent/monitor/execution_monitor.py` | Task and step status tracking |
| Core orchestration | `agent/core.py` | Chat management, plan execution, response formatting |

#### API endpoints

- `POST /agent/chat` - chat endpoint that returns Agent plan/draft/status response.
- `GET /agent/status` - latest Agent task status.
- `GET /agent/status/{task_id}` - task status by id.
- `WS /agent/ws` - realtime chat endpoint, returning `response` and available `status` events.

#### Usage examples

```bash
# Simple dry-run/proposal
curl -X POST http://localhost:8085/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "create ods_user table"}'

# Lineage query plan
curl -X POST http://localhost:8085/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "query ods_user"}'

# Latest status
curl http://localhost:8085/agent/status
```

#### Frontend chat components

- `AgentChat.vue` - main chat window with message list, input box, status panel, and ODS+DWD-first prompt chips.
- `ChatMessage.vue` - single message renderer with Markdown support.
- `TaskExecution.vue` / `ExecutionProgress.vue` - compact task progress display used by the Agent panel.

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

## Frontend pages (slim default)

Default profile keeps only the Agent-first core entry points:

| Path | Page | Purpose |
|---|---|---|
| `/` | ModelingDashboard | Agent workspace and conversational ODS+DWD planning |
| `/tasks` | TaskList | Task list, filtering, retry |
| `/tasks/:id` | TaskDetail | Task detail + SSE progress |
| `/artifacts` | ArtifactsView | DDL/DML artifact archive |

Set `VITE_ENABLE_ADVANCED_TOOLS=true` to additionally show backstage tools such as modeling forms, DI, datasources, governance, semantic hub, sync, SQL import, DWD JSON workbench, pipeline queue, and settings.

## Backend routes (slim default)

Default profile mounts Agent-first and existing modeling-loop routes. L1-L5 skeleton routes are opt-in.

| Prefix | Module | Default |
|---|---|---|
| `/agent` | Agent conversational ODS+DWD / planning | enabled |
| `/api/modeling` | Modeling task CRUD + SSE | enabled |
| `/api/dwd` | DWD modeling | enabled |
| `/api/pipeline` | Persistent pipeline queue | enabled |
| `/api/deploy` | Batch deploy | enabled |
| `/api/governance` | Governance checks | enabled |
| `/api/sync` | Dev/prod sync | enabled |
| `/api/cookie` | Cookie management | enabled |
| `/api/lineage` | Lineage tracing | enabled |
| `/api/import` | SQL import | enabled |
| `/api/roots` | Word-root validation | enabled |
| `/api/artifacts` | Artifacts | enabled |
| `/api/monitor` | Dashboard + WebSocket monitor | enabled |
| `/api/logs` | Task logs | enabled |
| `/api/workspace` | Datasource and workspace helpers | enabled |
| `/api/semantic` | Semantic skeleton | `ENABLE_EXPERIMENTAL_PLATFORM_ROUTES=true` only |
| `/api/runtime` | Runtime skeleton | `ENABLE_EXPERIMENTAL_PLATFORM_ROUTES=true` only |
| `/api/mcp-server` | MCP Server skeleton | `ENABLE_EXPERIMENTAL_PLATFORM_ROUTES=true` only |

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

- Core warehouse modeling loops above are productionized; section 8 Semantic / Agent Runtime (L0-L5) remains skeleton-level and is hidden by default, so it should not be treated as equally production-ready.
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

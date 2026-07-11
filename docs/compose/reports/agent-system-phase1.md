---
feature: agent-system-phase1
status: delivered
specs:
  - docs/compose/specs/2026-07-10-agent-system-design.md
plans:
  - docs/compose/plans/2026-07-10-agent-system-phase1.md
branch: master
commits: bc419b2..3105a7b
---

# Agent 系统 Phase 1 — Final Report

## What Was Built

Agent 系统 Phase 1 实现了对话式数仓操作 MVP，用户可以通过自然语言与数仓助手交互，完成创建表、查询血缘、检查状态等操作。系统采用 NLU → Planner → Executor 三段式架构，将用户意图解析为可执行的任务计划，然后通过工具执行器完成操作。

核心功能包括：基于正则表达式的意图识别（支持 create_table、query_lineage、check_status 三种意图）、任务规划器（模板匹配 + TaskGraph 依赖验证）、任务执行器（按依赖顺序执行步骤）、WebSocket 实时通信、以及前端对话界面组件。

## Architecture

### 核心组件

```
dataworks_agent/agent/
├── __init__.py           # 模块导出
├── core.py               # ChatAgent 核心类
├── nlu/                  # 自然语言理解
│   ├── intent_parser.py  # 意图解析器
│   ├── entity_extractor.py # 实体抽取
│   └── templates.py      # 意图模板
├── planner/              # 任务规划
│   ├── task_planner.py   # 任务规划器
│   └── task_graph.py     # 任务依赖图
└── executor/             # 执行引擎
    ├── task_executor.py  # 任务执行器
    └── tool_executor.py  # 工具执行器
```

### 数据流

1. 用户输入 → `ChatAgent.chat(message)`
2. NLU 解析 → `IntentParser.parse(message)` → `Intent(action, params, confidence)`
3. 任务规划 → `TaskPlanner.plan(intent)` → `TaskPlan(steps, task_id)`
4. 任务执行 → `TaskExecutor.execute(plan)` → `ExecutionResult(success, step_results)`
5. 响应构建 → `ChatResponse(message, success, data, error)`

### API 端点

- `POST /agent/chat` — HTTP 聊天接口
- `WS /agent/ws` — WebSocket 实时通信

### 前端组件

- `AgentChat.vue` — 主对话窗口
- `ChatMessage.vue` — 消息渲染（支持 Markdown + DOMPurify 消毒）
- `QuickActions.vue` — 快捷操作按钮

### Design Decisions

1. **ChatAgent 包装现有 Agent**：避免与 `runtime.agent.Agent` 命名冲突，提供简化的对话接口
2. **正则表达式意图识别**：Phase 1 使用规则匹配，后续可扩展 LLM
3. **TaskGraph 验证依赖**：即使模板是线性链，也使用图验证确保无循环
4. **ToolExecutor stub 实现**：预留扩展点，后续集成真实工具层

## Usage

### 后端启动

```bash
uv run python -m dataworks_agent.main
```

服务监听 `http://localhost:8085`

### API 调用

```bash
# 创建表
curl -X POST http://localhost:8085/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "创建ods_user表"}'

# 查询血缘
curl -X POST http://localhost:8085/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查询ods_user的血缘"}'
```

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端默认 `http://localhost:5173`，点击右下角 FAB 按钮打开对话窗口。

### 支持的意图

| 意图 | 示例输入 | 执行步骤 |
|------|----------|----------|
| create_table | "创建ods_user表" | 4 步 (Holo → MC → Node → DML) |
| query_lineage | "查询ods_user的血缘" | 1 步 (query_lineage) |
| check_status | "检查任务状态" | 1 步 (check_task_status) |

## Verification

### 测试覆盖

- **单元测试**: 23 个（NLU、Planner、Executor、Core）
- **路由测试**: 8 个（HTTP + WebSocket）
- **集成测试**: 9 个（完整链路）
- **总计**: 40 个测试全部通过

### 关键测试场景

1. 意图解析：正常输入、否定句、未知意图
2. 任务规划：create_table 4 步骤、query_lineage 1 步骤
3. 依赖验证：TaskGraph 循环检测
4. API 端点：正常请求、空消息校验、错误处理
5. WebSocket：消息处理、断连清理、异常处理

### 安全验证

- XSS 防护：DOMPurify 消毒 markdown 渲染
- 输入验证：Pydantic `Field(min_length=1, max_length=10000)`
- 否定词检测："不要创建表" 不会触发创建操作

## Journey Log

- [lesson] `AgentResponse.data` 类型 bug：`default_factory=list` 应为 `dict`，在集成时发现并修复
- [pivot] NLU 从 LLM 改为正则匹配：Phase 1 简化实现，降低依赖
- [lesson] WebSocket prefix 重复：router 和 main.py 都添加 prefix 会导致路径错误
- [lesson] fixture 异常安全性：测试 fixture 必须用 try/finally 保护 teardown
- [pivot] ChatAgent 命名：避免与 runtime.agent.Agent 冲突，改用 ChatAgent

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-07-10-agent-system-design.md` | 初始设计 | 已根据 Phase 1 范围调整 |
| `docs/compose/plans/2026-07-10-agent-system-phase1.md` | 实现计划 | 10 个任务全部完成 |
| `docs/compose/reports/code-review-report.md` | 代码评审 | 发现并修复多个问题 |
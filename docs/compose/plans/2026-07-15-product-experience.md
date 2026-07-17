# DataWorks Agent 产品体验提升 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除多余测试、完善连续对话持久化、激活多智能体协作、集成MCP/Skill、美化页面端，让用户能在网页上流畅使用。

**Architecture:** 最小改动原则 — 只删测试、只加持久化、只路由Agent、只美化CSS，不动核心业务逻辑。

**Tech Stack:** Python 3.12+, Vue 3 + Element Plus, SQLite (via aiosqlite), LangGraph

## Global Constraints
- 不引入新的第三方依赖（测试删除、对话持久化、Agent路由都用已有库）
- 前端改动仅限CSS和布局，不重写Vue组件逻辑
- 后端改动不修改workflow_service.py的核心执行逻辑
- 所有改动必须向后兼容，不影响现有API

---

## Task 1: 删除多余测试文件

**Covers:** [S1] 精简测试

**Files:**
- Delete: `tests/unit/test_standards_loader.py` (5 funcs, 36 lines, 低价值)
- Delete: `tests/unit/test_app_route_profile.py` (2 funcs, 30 lines, 纯路由检查)
- Delete: `tests/unit/test_intent_dispose.py` (3 funcs, 51 lines, 简单DB操作)
- Delete: `tests/unit/test_verify_autonomous_query.py` (1 func, 18 lines, 仅加载JSON)
- Delete: `tests/unit/test_table_name.py` (10 funcs, 95 lines, 逻辑简单)
- Delete: `tests/unit/test_agent/test_task_executor.py` (5 funcs, 75 lines, 注释说明是桩代码)
- Delete: `tests/unit/test_cookie_sync.py` (2 funcs, 合并到test_cookie_health.py)
- Delete: `tests/unit/test_agent_api.py` (4 funcs, 重复test_agent_router.py)
- Delete: `tests/integration/test_release_smoke.py` (5 funcs, 重复health check)
- Delete: `tests/integration/test_mocked_fixture.py` (1 func, 重复health check)
- Delete: `tests/integration/test_modeling_api.py` 中的 health_check 测试
- Delete: `tests/integration/test_datasource_api.py` (合并到test_data_integration_api.py)

**Interfaces:**
- Consumes: 无
- Produces: 删除12个测试文件，保留约1000个有效测试

**Steps:**
1. 备份当前tests目录
2. 逐个删除低价值测试文件
3. 运行剩余测试确认不破坏

---

## Task 2: 对话记忆持久化

**Covers:** [S2] 连续对话持久化

**Files:**
- Create: `dataworks_agent/agent/conversation_store.py` — SQLite持久化存储
- Modify: `dataworks_agent/agent/core.py:78-82` — 使用持久化存储替代内存dict

**Interfaces:**
- Consumes: `dataworks_agent/agent/core.py` 的 `_conversation_memories` dict
- Produces: `ConversationStore` 类，支持 `save(conversation_id, user_msg, assistant_msg)` 和 `load(conversation_id) -> list[tuple[str, str]]`

**Steps:**
1. 创建 `conversation_store.py`，实现SQLite读写
2. 修改 `core.py` 的 `__init__` 使用 `ConversationStore`
3. 修改 `_save_conversation_history` 和 `_get_conversation_history` 使用持久化存储
4. 测试：重启服务后对话历史仍存在

---

## Task 3: 激活多智能体协作

**Covers:** [S3] 6个Agent路由

**Files:**
- Modify: `dataworks_agent/agent/core.py:170-210` — 在 `_route_action` 中集成6个专业Agent
- Modify: `dataworks_agent/runtime/agent.py` — 完善 `ModelingAgent` 和 `QueryAgent` 的 stub 方法

**Interfaces:**
- Consumes: `dataworks_agent/runtime/agent.py` 的6个Agent类
- Produces: `ChatAgent._route_action` 根据意图路由到专业Agent

**Steps:**
1. 在 `core.py` 中导入6个Agent类
2. 修改 `_route_action` 方法，根据 action 类型路由到对应Agent
3. 完善 `ModelingAgent.process()` 调用 `ForwardModelingFlow`
4. 完善 `QueryAgent.process()` 调用 `CaliberClarifier` + SQL执行
5. 测试：不同意图路由到不同Agent

---

## Task 4: MCP和Skill集成

**Covers:** [S4] MCP/Skill调用

**Files:**
- Modify: `dataworks_agent/agent/core.py` — 添加MCP工具调用和Skill触发逻辑
- Modify: `dataworks_agent/runtime/agent.py` — 在Agent中集成MCP/Skill

**Interfaces:**
- Consumes: 现有MCP客户端（`dataworks_agent/mcp/official_dataworks.py`）
- Produces: Agent能通过MCP调用外部工具，通过Skill触发专项能力

**Steps:**
1. 在 `ChatAgent` 中注入MCP客户端
2. 当意图匹配MCP工具时，直接调用MCP工具
3. 当意图匹配Skill时，触发对应Skill逻辑
4. 测试：MCP工具调用和Skill触发

---

## Task 5: 页面端美化

**Covers:** [S5] UI重构

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue` — 侧边栏美化
- Modify: `frontend/src/components/agent/AgentChat.vue` — 聊天区域美化
- Modify: `frontend/src/components/agent/ChatMessage.vue` — 消息气泡美化
- Modify: `frontend/src/App.vue` — 全局样式优化

**Interfaces:**
- Consumes: 现有Vue组件结构
- Produces: 现代化、专业的UI设计

**Steps:**
1. 优化侧边栏：品牌logo、导航图标、状态指示
2. 美化聊天区域：消息气泡、输入框、发送按钮
3. 优化欢迎面板：渐变背景、提示词卡片
4. 添加微交互：hover效果、加载动画、滚动行为
5. 测试：页面在不同分辨率下正常显示

---

## Task 6: 端到端真实页面测试

**Covers:** [S6] 验证所有功能

**Files:**
- No code changes
- Manual testing via browser at http://127.0.0.1:8085

**Steps:**
1. 启动后端和前端
2. 测试问候语："你好" → 返回欢迎消息
3. 测试连续对话：第二轮消息应携带上下文
4. 测试多智能体：发送建模请求 → 路由到ModelingAgent
5. 测试MCP：发送数据查询请求 → 调用MCP工具
6. 测试Skill：发送诊断请求 → 触发诊断Skill
7. 验证页面美观度和交互流畅性

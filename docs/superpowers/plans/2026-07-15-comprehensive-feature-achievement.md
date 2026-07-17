# 全面功能达成 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 达成连续对话、多智能体协作、MCP/skill/rules支持、美化前端、真实网页端测试全部功能。

**Architecture:** 基于现有 Vue 3 + Element Plus + FastAPI 栈，修复关键bug、集成MCP/Skill到Agent、重构前端视觉。

**Tech Stack:** Vue 3, Element Plus, Vite, FastAPI, Starlette, WebSocket, LLM (Agnes AI)

## Global Constraints

- 用户只关心页面端体验，不关心测试覆盖率
- 用户偏好简洁、美观的前端界面
- 达成目标前不停止迭代
- 后端端口 8085，前端开发端口 3000
- LLM API: agnes-1.5-flash @ https://apihub.agnes-ai.com/v1

---

### Task 1: 修复后端关键Bug — execution_mode 传递

**Files:**
- Modify: `dataworks_agent/routers/agent.py:109-115`
- Modify: `dataworks_agent/agent/core.py:182`

**Interfaces:**
- Consumes: ChatRequest.execution_mode field
- Produces: workflow execution with proper execution_mode propagation

- [ ] **Step 1: 修复 REST 端点 execution_mode 缺失问题**

  `routers/agent.py:109-115` 中当 `workflow_options_explicit` 为 False 时调用 `_agent.chat()` 不传 `execution_mode`。在 `core.py:182` 中 `execution_mode is not None` 会阻断 workflow 执行。

  修复：REST 端点在不传 execution_mode 时默认使用 `"plan"` 模式（与 WebSocket 端点一致）。

```python
# routers/agent.py 第109-115行修改为：
if not workflow_options_explicit:
    if payload.request_type is None:
        response = await _agent.chat(
            payload.message,
            execution_mode="plan",
            conversation_id=payload.conversation_id,
        )
    else:
        response = await _agent.chat(
            payload.message,
            payload.request_type,
            execution_mode="plan",
            conversation_id=payload.conversation_id,
        )
```

- [ ] **Step 2: 验证修复**

  启动后端，用 curl 测试 `/agent/chat` 不带 execution_mode 时能正常返回 plan 结果。

**Commit:** `fix: REST endpoint passes default execution_mode to workflow`

---

### Task 2: 完善连续对话能力 — 持久化对话历史

**Files:**
- Modify: `dataworks_agent/agent/conversation_graph.py`
- Modify: `dataworks_agent/db/database.py`
- Modify: `dataworks_agent/routers/agent.py`

**Interfaces:**
- Consumes: conversation_id from client
- Produces: persistent conversation context across restarts

- [ ] **Step 1: 检查 ConversationGraph 是否持久化**

  读取 `conversation_graph.py` 确认 `_checkpointer` 是否写入 SQLite。如果没有，添加持久化层。

- [ ] **Step 2: 确保 conversation_id 在前端保持**

  `AgentChat.vue:381` 使用 `idempotencyKey()` 生成 conversation_id，但刷新页面会丢失。修改为 localStorage 持久化。

```typescript
// AgentChat.vue 修改 conversationId 初始化
const storedId = localStorage.getItem('conversation_id')
const conversationId = ref(storedId || idempotencyKey())

// 每次发送消息后保存
function resetConversation() {
  conversationId.value = idempotencyKey()
  localStorage.setItem('conversation_id', conversationId.value)
  // ...
}
```

- [ ] **Step 3: 验证连续对话**

  发送消息 → 刷新页面 → 发送"总结" → 应能读到上次对话上下文。

**Commit:** `feat: persistent conversation history with localStorage`

---

### Task 3: 集成 MCP 到 Agent 工作流

**Files:**
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/state.py`
- Modify: `dataworks_agent/mcp/official_dataworks.py`

**Interfaces:**
- Consumes: app_state._official_mcp_client
- Produces: MCP tool calls from Agent workflow

- [ ] **Step 1: 确认 MCP 客户端已注册到 app_state**

  `main.py:164-171` 已创建 `app_state._official_mcp_client`。确认其暴露了可用的 tool 列表。

- [ ] **Step 2: 在 Agent 意图分类中加入 MCP 能力**

  修改 `core.py:_classify_intent_with_llm()` 的 instruction prompt，告知 LLM 当前可用的 MCP 工具列表。

- [ ] **Step 3: 实现 MCP 工具调用桥接**

  在 workflow_service.py 中添加 `_call_mcp_tools()` 方法，根据意图调用对应 MCP 工具。

- [ ] **Step 4: 在 capabilities 中暴露 MCP 状态**

  `core.py:capability_status()` 返回的字典中包含 MCP 连接状态。

**Commit:** `feat: integrate MCP tools into Agent workflow`

---

### Task 4: 集成 Skill 系统到 Agent

**Files:**
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/agent/nlu/templates.py`

**Interfaces:**
- Consumes: skill definitions from .codex/skills/ and .mimocode/skills/
- Produces: skill-triggered specialized behaviors

- [ ] **Step 1: 扫描可用 Skill 列表**

  读取项目中的 skill 定义文件（`.codex/skills/`, `.mimocode/skills/`, `.agents/skills/`），生成可用 skill 列表。

- [ ] **Step 2: 在意图分类 prompt 中注入 skill 信息**

  修改 `_classify_intent_with_llm()` 的 instruction，告知 LLM 可用的 skill 及其触发条件。

- [ ] **Step 3: 实现 skill 触发和执行**

  当 LLM 返回的 intent 匹配某个 skill 时，调用对应的 skill handler。

- [ ] **Step 4: 在 capabilities 中暴露 Skill 状态**

  让前端知道哪些 skill 可用。

**Commit:** `feat: integrate skill system into Agent workflow`

---

### Task 5: 前端页面美化 — 整体重构

**Files:**
- Modify: `frontend/src/App.vue` — 全局样式
- Modify: `frontend/src/layouts/MainLayout.vue` — 侧边栏和顶部栏
- Modify: `frontend/src/components/agent/AgentChat.vue` — 聊天界面
- Modify: `frontend/src/components/agent/ChatMessage.vue` — 消息气泡
- Modify: `frontend/index.html` — 页面标题和 favicon

**Interfaces:**
- Consumes: existing component structure
- Produces: modern, professional UI with improved UX

- [ ] **Step 1: 设计新的视觉体系**

  采用深色侧边栏 + 浅色主内容的专业数据平台风格：
  - 主色：`#4F46E5`（靛蓝）
  - 辅助色：`#06B6D4`（青色）
  - 背景：`#F8FAFC`（浅灰蓝）
  - 侧边栏：`#1E293B`（深蓝灰）
  - 字体：系统字体栈

- [ ] **Step 2: 重构 MainLayout 侧边栏**

  深色侧边栏，品牌logo居中，导航项带 hover 动画效果。

- [ ] **Step 3: 重构 AgentChat 聊天界面**

  - 欢迎页：简洁的居中布局，品牌渐变 orb，4个快捷提示卡片
  - 消息气泡：区分用户/AI，带时间戳和头像
  - 输入框：固定在底部，支持 Enter 发送，Shift+Enter 换行
  - 结果卡片：优雅的折叠面板展示技术详情
  - 发布审批：醒目的确认按钮

- [ ] **Step 4: 添加过渡动画**

  - 页面切换淡入淡出
  - 消息出现动画
  - 按钮 hover 微交互

- [ ] **Step 5: 响应式设计**

  移动端侧边栏收起为汉堡菜单。

**Commit:** `feat: complete UI redesign with modern professional theme`

---

### Task 6: 修复 Vite 开发和构建配置

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `dataworks_agent/main.py` (CORS)

**Interfaces:**
- Consumes: Vite dev server config
- Produces: working dev + build pipeline

- [ ] **Step 1: 统一端口配置**

  Vite 默认 5173，但 CORS 配置了 3000。修改 vite.config.ts 使用 5173 并在 CORS 中添加。

- [ ] **Step 2: 修复前端构建**

  运行 `npm run build` 确保 dist 目录有输出。

- [ ] **Step 3: 修复 SPA fallback**

  确保后端静态文件服务正确返回 index.html。

**Commit:** `fix: unify port config and ensure frontend builds`

---

### Task 7: 端到端真实测试

**Files:**
- Run: backend `python -m dataworks_agent.main`
- Run: frontend `npm run dev`
- Browser test at http://127.0.0.1:5173

**Interfaces:**
- Consumes: running backend + frontend
- Produces: verified working system

- [ ] **Step 1: 启动后端**

  `uv run python -m dataworks_agent.main` 确认端口 8085 正常启动，无报错。

- [ ] **Step 2: 启动前端开发服务器**

  `cd frontend && npm run dev` 确认端口 5173 正常启动。

- [ ] **Step 3: 浏览器测试 — 连续对话**

  打开 http://127.0.0.1:5173，发送消息 → 刷新页面 → 发送"总结" → 验证上下文保持。

- [ ] **Step 4: 浏览器测试 — Agent 能力**

  尝试正向建模、逆向建模、异常排查、问数等快捷提示，验证各路径正常。

- [ ] **Step 5: 浏览器测试 — WebSocket 实时连接**

  验证顶部的"实时连接"状态指示器正常工作。

- [ ] **Step 6: 浏览器测试 — 其他页面**

  测试任务运行、产物中心等页面是否正常加载。

**Commit:** `test: end-to-end verification of all features`

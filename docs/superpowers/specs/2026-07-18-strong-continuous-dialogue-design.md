# 强连续对话、混合交互卡片与可观测验收设计

- 日期：2026-07-18
- 状态：已完成产品设计确认，待用户审核书面规格
- 适用范围：Web Agent 对话入口、`POST /agent/chat`、`GET /agent/messages` 及相关会话状态

## 1. 背景与问题

项目已经实现 `PendingInteraction`、卡片渲染、部分会话检查点和历史恢复，但实际体验尚未达到“可靠的连续对话”。现状主要有四个缺口：

1. 结构化卡片只覆盖少数澄清流程。问候、未知意图和普通追问通常只返回文本。
2. 连续性主要围绕活动 `pending_interaction` 和少量参数合并，不能稳定理解“什么意思”“继续”“第二个”“刚才那张表”等自然表达。
3. 部分关键上下文仍保存在进程内，例如查询 frame，服务重启后可能丢失。
4. 现有连续对话脚本偏向打印式冒烟，没有充分断言；日志也无法按会话、轮次和交互 ID 串联完整事件链。

已确认的产品选择：

- 卡片策略：混合策略；
- 连续性：强连续性；
- 恢复范围：刷新页面和服务重启后恢复同一会话；
- 完成标准：必须通过完整多轮测试并生成可排查的运行日志包。

## 2. 目标

本次设计实现以下结果：

1. 用户短句能够结合当前任务、上一条助手回复、已选资源和活动卡片理解。
2. 问候、解释和查看上下文不会意外清空或消费当前任务。
3. 问候和意图不明确时提供入口卡片；分支、澄清、确认和任务完成时提供上下文相关卡片。
4. 页面刷新和服务重启后恢复消息、任务状态、已选资源和活动卡片。
5. 旧卡片、重复提交和并发页面不能造成重复执行或 stale write。
6. 每轮对话具备结构化、可关联、可脱敏的运行日志。
7. 完成报告必须包含后端、前端、浏览器、多轮稳定性和恢复测试证据。

## 3. 非目标

本阶段不实现：

- ChatGPT 式多会话列表、重命名、搜索和归档 UI；
- 跨账号或跨设备同步；
- 无限长期记忆或未经确认的用户画像；
- 让 LLM 直接决定 DataWorks 写操作；
- 通过测试创建 DataWorks 目录、真实节点或其他线上写入资源；
- 重写现有找表、问数、建模、血缘或排障工作流。

## 4. 总体方案

采用“确定性会话状态机 + 语义承接层 + 现有业务工作流”的组合方案。

```text
用户消息
  ↓
加载持久化会话状态
  ↓
Context Resolver
  ├─ 确定性解析：选项编号、继续、取消、重置、明确参数修改
  ├─ 上下文解析：解释上一条、资源指代、延续当前目标
  └─ 低置信度语义解析：受限 LLM 兜底
  ↓
ResolvedTurn：完整业务请求 + 对话动作 + 上下文更新
  ↓
现有 NLU → 现有工作流 → 现有安全护栏
  ↓
Response Policy：自然语言回复 + 可选结构化 interaction
  ↓
持久化消息、状态、活动卡片和事件日志
```

### 4.1 设计原则

- 确定性优先：能够可靠识别的短句不调用 LLM。
- LLM 只做理解：LLM 输出必须经过结构化模型和安全校验，不直接执行写操作。
- 单一活动交互：同一会话同一时刻最多一个 `pending` interaction。
- 显式版本控制：所有交互回答必须携带状态版本。
- 最小上下文：仅加载相关历史、任务摘要、已选资源和活动交互，不无限发送完整历史。
- 向后兼容：现有工作流结果继续可转换为统一 interaction，不一次性重写业务模块。

## 5. 对话动作模型

Context Resolver 将每轮输入归一化为以下动作：

| 动作 | 示例 | 处理方式 |
|---|---|---|
| `new_goal` | “查一下订单表” | 新建活动业务目标，归档旧目标状态 |
| `answer` | “第二个”“选 DWD” | 回答当前活动 interaction |
| `continue` | “继续”“下一步” | 延续当前任务并进入下一阶段 |
| `explain` | “什么意思”“为什么” | 解释上一条回复，不消费活动 interaction |
| `modify` | “换成 DWD”“不要执行” | 修改当前任务参数并重新计算下一步 |
| `refer` | “刚才那张表”“用它” | 解析当前已选资源或最近明确资源 |
| `cancel` | “取消这个任务” | 终止当前活动任务，保留历史 |
| `greeting` | “你好” | 回应问候并保留当前任务和卡片 |
| `reset` | 点击“新会话” | 生成新的 conversation ID，清空新会话上下文 |
| `clarify` | 无法可靠判断 | 返回澄清卡片或自由输入提示 |

### 5.1 解析顺序

1. 验证显式 `interaction_answer`。
2. 检查是否存在活动 interaction，并解析自然语言选项回答。
3. 识别显式 reset、cancel、continue、explain、greeting 和 modify。
4. 解析资源指代与上下文参数。
5. 判断是否为明确的新业务目标。
6. 仍不确定时调用受限 LLM 分类器。
7. 低于置信度阈值时返回 `clarify`，不得静默猜测。

### 5.2 ResolvedTurn

承接层输出稳定的内部协议：

```json
{
  "turn_id": "turn_xxx",
  "dialogue_action": "explain",
  "rewritten_message": "请解释上一条关于订单候选表差异的回复",
  "context_updates": {},
  "resolved_references": [],
  "resolver": "deterministic",
  "confidence": 1.0,
  "consume_interaction": false
}
```

## 6. 会话状态

每个 conversation 持久化以下信息：

```text
conversation_id
active_goal
current_action
task_status
resolved_params
selected_resources
pending_interaction
last_assistant_turn
conversation_summary
state_version
updated_at
```

### 6.1 字段职责

- `active_goal`：当前业务目标，不由短句覆盖。
- `current_action`：当前工作流动作。
- `resolved_params`：已经确认的业务参数。
- `selected_resources`：表、节点、任务等完整资源标识符。
- `pending_interaction`：当前唯一有效卡片交互。
- `last_assistant_turn`：支持“什么意思”“为什么这么选”。
- `conversation_summary`：保存已确认背景，限制上下文大小。
- `state_version`：防止并发覆盖、重复消费和旧卡片执行。

关键连续对话状态不得只保存在 `_query_frames` 等进程内结构中。需要跨重启使用的内容必须进入持久化会话状态。

## 7. 混合卡片策略

### 7.1 统一回复协议

```json
{
  "message": "自然语言回复",
  "interaction": {
    "interaction_id": "int_xxx",
    "type": "single_select",
    "purpose": "select_table",
    "prompt": "请选择候选表",
    "options": [],
    "allow_custom_input": true,
    "state_version": 3
  },
  "conversation": {
    "conversation_id": "conv_xxx",
    "active_goal": "查找订单相关表",
    "status": "waiting_user",
    "state_version": 3
  }
}
```

`interaction` 可以为空，但只要存在，就必须通过后端模型校验。`next_actions` 不再混用字符串与对象作为前端主要交互协议。

### 7.2 展示规则

| 场景 | 行为 |
|---|---|
| 首次问候 | 展示智能问数、查找数据表、数仓建模、异常排查等入口卡片 |
| 意图不明确 | 展示 2～4 个可能任务入口，并允许自定义输入 |
| 多候选或多分支 | 展示真实可提交的候选卡片 |
| 高风险操作 | 展示确认、修改方案、取消卡片 |
| 任务完成 | 展示与当前结果相关的下一步卡片 |
| 纯解释 | 不生成无关卡片；若任务未完成，保留当前活动卡片 |
| 中途问候 | 回应问候，并重新展示当前任务卡片 |
| 无合理选项 | 仅文本和自由输入，不制造虚假按钮 |

### 7.3 生命周期

```text
pending → answered | cancelled | expired
```

- 点击卡片提交 `interaction_id + option_id + state_version`。
- “第二个”等自然语言回答与点击对应卡片使用同一服务端解析路径。
- explain 和 greeting 不消费 interaction。
- 回答成功后旧 interaction 失效。
- 新 interaction 产生后，旧消息中的卡片显示已失效。
- 点击过期卡片时，服务端返回最新状态；前端自动同步最新 interaction。

## 8. 持久化与恢复

### 8.1 会话身份

- 前端首次进入生成 UUID 并写入 `localStorage`。
- 刷新页面继续使用同一 UUID。
- 服务重启不改变 UUID。
- 点击“新会话”生成新 UUID。
- 不使用客户端 IP 作为 conversation ID。
- 本阶段不增加多会话列表，但不误删旧会话数据。

### 8.2 页面恢复顺序

```text
读取 localStorage conversation_id
  ↓
GET /agent/messages
  ↓
恢复消息历史
  ↓
恢复任务摘要、已选资源、状态版本和 active_interaction
  ↓
将活动 interaction 绑定到对应助手消息
  ↓
允许点击或自然语言继续
```

### 8.3 崩溃一致性

- 每轮生成唯一 `request_id` 和 `turn_id`。
- 写操作前保存可恢复的意图与状态版本，但不得把“计划执行”误记为“已经执行”。
- 消息已保存而状态未保存时，以最后一个完整状态版本为准，并提示重新提交。
- interaction 回答必须幂等；相同答案重放不能再次触发业务写入。
- 状态保存使用版本比较，拒绝 stale write。

## 9. 并发与安全

- 两个页面操作同一会话时，后提交的旧版本请求返回 `interaction_expired` 或 `state_conflict`。
- 服务端响应包含最新 conversation 状态和活动 interaction，前端据此自愈。
- 解释、问候、上下文摘要均为只读操作。
- 节点创建、修改、删除和发布继续经过既有 guard 与 Publish Gate。
- 所有 DataWorks 节点操作继续遵守项目目录硬规则：禁止创建目录；父目录必须只读确认存在；同路径同名节点必须复用 UUID。
- 自动测试不得执行未经授权的真实 DataWorks 写入。
- 日志必须脱敏 AK/SK、Cookie、Authorization、个人信息和敏感 SQL。

## 10. 可观测性设计

### 10.1 当前缺口

- `main._setup_logging()` 标注为 JSON 日志，实际格式仍为普通文本。
- `/logs` 主要面向 task step，无法按 conversation、turn 或 interaction 查询。
- 当前连续对话脚本只打印部分响应，没有足够断言。

### 10.2 对话事件日志

新增轮转 JSONL 日志。每条事件包含：

```json
{
  "timestamp": "2026-07-18T15:00:00+08:00",
  "level": "INFO",
  "event": "turn_resolved",
  "request_id": "req_xxx",
  "conversation_id": "conv_xxx",
  "turn_id": "turn_xxx",
  "interaction_id": "int_xxx",
  "state_version_before": 3,
  "state_version_after": 4,
  "dialogue_action": "explain",
  "resolver": "deterministic",
  "confidence": 1.0,
  "action_before": "ask_data",
  "action_after": "ask_data",
  "pending_interaction_preserved": true,
  "duration_ms": 18,
  "outcome": "success"
}
```

### 10.3 事件链

每轮至少覆盖：

```text
turn_received
context_loaded
turn_classified
reference_resolved
nlu_parsed
workflow_started
workflow_finished
interaction_emitted
state_persisted
response_sent
```

异常事件必须包含：

- 错误类型、错误码和完整堆栈；
- 失败阶段；
- 状态是否保存；
- 当前状态版本；
- 是否可能已经产生业务写操作。

### 10.4 查询能力

日志查询至少支持：

- `conversation_id`
- `request_id`
- `turn_id`
- `interaction_id`
- `event`
- `level`
- 时间范围

## 11. 测试设计

### 11.1 对话承接测试

采用表驱动测试覆盖：

- 问候、继续、解释、取消、重置；
- 第一个、第二个、最后一个；
- 刚才那个、这张表、用它；
- 修改分层、时间范围和执行模式；
- 任务切换与旧参数隔离；
- 同义表达、口语、错别字和短句；
- 无有效指代时的澄清；
- LLM 兜底输出校验和低置信度降级。

### 11.2 API 集成测试

覆盖：

- 消息、状态、卡片和版本持久化；
- 点击卡片与自然语言回答等价；
- explain/greeting 不消费 interaction；
- 回答后旧卡片失效；
- 页面刷新恢复；
- 新 ChatAgent 实例恢复；
- 服务重启恢复；
- 重复提交幂等；
- stale state_version；
- 双页面并发；
- 新旧任务参数隔离；
- 空状态和损坏状态安全降级。

### 11.3 前端测试

覆盖：

- 入口、候选、确认、下一步卡片；
- 自定义输入；
- pending、answered、expired 状态；
- 解释后保留卡片；
- 刷新后绑定正确消息；
- 旧卡片不可重复触发；
- 请求失败后的重试；
- 无重复消息和重复卡片。

### 11.4 浏览器端到端旅程

至少实现 8 条完整旅程，每条连续 5～10 轮：

1. 问候 → 查表 → 解释 → 选第二项 → 查看字段；
2. 查表 → 限定 DWD → 最近七天 → 只生成方案；
3. 建模 → 补充源表 → 修改分层 → 取消；
4. 候选卡片 → 刷新 → 自然语言选择；
5. 候选卡片 → 重启后端 → 继续；
6. 双页面并发 → 旧卡片失效；
7. 任务切换 → 验证旧参数未污染；
8. 模糊输入 → 澄清 → 自定义回答 → 正确恢复。

另增加 50 轮混合对话稳定性测试，验证：

- 状态版本单调递增；
- interaction 不重复消费；
- 上下文大小有界；
- 不发生跨任务参数污染；
- 数据库状态与页面状态一致。

## 12. 测试日志包

每次完整验收输出：

```text
reports/continuous-dialogue/<run-id>/
├── summary.md
├── conversation-transcript.json
├── backend-events.jsonl
├── frontend-console.json
├── network-events.json
├── test-results.xml
├── screenshots/
└── failures/
```

`summary.md` 必须包含：

- Git commit；
- 测试环境；
- 实际执行命令；
- 各多轮旅程结果；
- 失败和重试次数；
- 浏览器控制台错误；
- 后端异常；
- 日志与截图位置；
- 是否发生真实 DataWorks 写入，默认必须为“否”。

日志包属于测试产物，不提交敏感运行数据到 Git。仓库只保留脱敏样例或格式说明。

## 13. 完成门槛

只有以下条件全部满足，才能报告完成：

```text
后端相关集成测试通过
前端交互测试通过
前端 build 通过
ruff 通过
8 条浏览器多轮旅程通过
50 轮稳定性测试通过
刷新与服务重启恢复通过
并发旧卡片测试通过
浏览器控制台无未解释错误
生成并人工检查完整日志包
未执行未经授权的真实 DataWorks 写入
```

任一条件失败，只能报告“尚未完成”、失败证据和当前根因，不能以“主要功能已完成”替代。

## 14. 预期修改范围

实现阶段预计只修改与本目标直接相关的模块：

- `dataworks_agent/agent/core.py`
- `dataworks_agent/agent/conversation_graph.py`
- `dataworks_agent/agent/interaction.py`
- 新增对话承接/回复策略模块，避免继续膨胀 `core.py`
- `dataworks_agent/routers/agent.py`
- `dataworks_agent/routers/logs.py`
- 对话状态或事件日志所需数据库模型与迁移
- `frontend/src/pages/SmartChatPage.vue`
- `frontend/src/components/agent/MessageBubble.vue`
- `frontend/src/components/agent/chatInteraction.ts`
- 相关后端集成测试、前端测试和浏览器 E2E
- `dataworks_agent/scripts/test_continuous_dialogue.py`，改为带断言和日志输出的验收入口，或由新的验收脚本替代

不顺带重构无关模块，不改变 Cookie/OpenAPI 能力分工，不扩大 DataWorks 写权限。

## 15. 关键验收示例

```text
用户：你好
Agent：自然问候，并展示任务入口卡片。

用户：我想查一下订单
Agent：返回订单相关候选及结构化卡片。

用户：什么意思
Agent：解释候选差异，保留同一个有效 interaction。

用户：第二个
Agent：服务端解析为第二项，消费旧 interaction，展示上下文相关的下一步卡片。

用户：继续
Agent：延续当前任务，不重新询问业务目标。
```

该路径必须在组件测试、API 集成测试和真实浏览器 E2E 中分别验证，并能够通过 conversation ID 获取完整事件日志。

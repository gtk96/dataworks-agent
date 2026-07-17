# DataWorks Agent 对话式交互与可恢复工作流设计

> 项目：`giikin_dw_agent` / DataWorks Agent
> 版本：v3.1
> 日期：2026-07-17
> 状态：已实施并通过回归验证
> 定位：本文件作为对话式 Agent 的主设计文档；早期 LangChain 集成报告和产品体验计划作为历史参考，不再单独代表当前实现状态。

## 1. 目标与结论

本次改造的目标不是让聊天页面“更像聊天”，也不是简单增加 Streaming 或把更多历史消息塞给 LLM，而是让用户能够通过自然语言和结构化选择，持续完成一个真实的数据工作流。

核心结论：

1. **对话历史不等于工作流状态。** 系统必须明确保存当前任务、待补充槽位、候选资源、用户选择和恢复节点。
2. **上下文注入仍然重要，但它只是基础设施。** Metadata、History、Project、Capability 等上下文需要参与理解，不能替代确定性的状态机和执行护栏。
3. **澄清必须结构化。** 候选表不能只藏在 `artifacts` 或技术详情中；后端应返回可选择的交互协议，前端应渲染候选卡片、确认按钮和下一步动作。
4. **LLM 负责理解和表达，确定性代码负责状态、标识符、安全和执行。** `project.table`、节点 ID、候选项 ID、审批状态等不能依赖 LLM 或正则重新猜测。
5. **每一轮都应推进任务。** 返回结果必须说明当前完成了什么、正在等待什么、用户可以做什么，而不是只给一段泛化文本。

目标体验：

```text
用户：查订单表
Agent：找到 32 张候选表，请先选择数据层级。
       [DWD 13] [DWS 3] [ODS 1] [其他 15]

用户点击：DWD
Agent：已缩小到 13 张 DWD 表，请选择目标表。
       [订单详情全量表]
       [第三方平台订单表]
       [订单物流节点表]
       ...

用户点击：订单详情全量表
Agent：已选择 giikin_aliyun.tb_dwd_ord_order_detail_di。
       你希望继续做什么？
       [预览数据] [查看字段] [查看分区] [查血缘] [生成 SQL]

用户点击：预览数据
Agent：执行只读查询，展示结果、执行通道、耗时和校验状态。
```

## 2. 当前实现基线

### 2.1 已具备的能力

当前项目已经具备对话式改造所需的主要基础组件：

- `POST /agent/chat`、WebSocket `/agent/ws` 和 SSE `/agent/chat/stream`。
- 前端持久化并发送 `conversation_id`。
- 请求支持 `context_updates`。
- `conversation_history` 保存用户和助手消息。
- `ConversationGraph` 使用 LangGraph checkpoint 保存部分结构化上下文。
- `AgentWorkflowService` 已支持 `ask_data`、建模、诊断、Cookie 管理等工作流。
- 自主问数已经能够通过 MetadataProvider、数据专辑和 Cookie/BFF 搜索中文业务表。
- 工作流已有 Loop 验收、只读 SQL 校验、查询通道回退和 Publish Gate。
- 前端已有计划、执行步骤、产物、错误和澄清问题的展示基础。

这些能力应继续复用，不需要重新搭建另一套聊天 Agent。

### 2.2 2026-07-17 实际复现

使用同一个 `conversation_id` 调用当前 `/agent/chat`：

| 输入 | 实际结果 | 耗时 |
|---|---|---:|
| `查订单表` | 找到 32 张候选表，返回 `needs_context` | 约 1.77 秒 |
| `只要 dwd` | 缩小为 15 张 DWD 候选表 | 约 1.64 秒 |
| `giikin_aliyun.tb_dwd_ord_order_detail_di` | 生成查询但丢失项目名前缀，最终查询失败 | 约 15.79 秒 |

因此，当前主要问题已经不是早期文档描述的“`查订单表` 被识别为 unknown”，而是：

1. 搜索结果已经存在，但没有变成清晰、可点击的候选交互。
2. 用户回答依靠“原始目标 + 补充信息”重新解析，没有按待回答问题精确恢复。
3. 完整表名在实体提取和参数合并过程中可能被截成裸表名。
4. 执行耗时较长时，页面缺少可理解的阶段反馈，用户感知为“卡住”。

### 2.3 文档与实现的偏差

早期文档中的以下内容应视为历史描述：

- “LangChain 已完整接入主 ChatAgent”不能仅根据存在 `LangChainChatAgent` 和 `LLMIntentClassifier` 文件判断；只有进入 `/agent/chat` 主链路并经过端到端验证的能力才算正式启用。
- “保存最近消息即可支持多轮对话”不成立。消息历史只能辅助理解，不能表达待回答问题和工作流恢复点。
- “先完成上下文注入，再做多轮引导”需要调整。结构化交互协议和可恢复状态应先落地，否则上下文越多，重新猜测越复杂。
- “Streaming 等于对话式体验”不成立。Streaming 解决等待感知，不能解决任务状态断裂。

## 3. 问题根因

### 3.1 会话上下文只有信息，没有交互契约

当前 `ConversationGraph` 主要保存：

- `objective`
- `action`
- `params`
- `workflow_state`
- `pending_objective`

但一次真正的澄清还需要保存：

- Agent 正在问哪个问题；
- 问题要求填写哪个槽位；
- 允许自由文本还是必须从候选中选择；
- 候选项的稳定 ID 和完整值；
- 用户回答后从哪个节点继续；
- 候选是否已经过期；
- 是否需要二次确认或人工审批。

缺少这些信息时，下一轮只能把文本拼回原目标重新跑 NLU，容易出现歧义、参数覆盖和标识符丢失。

### 3.2 候选数据存在，但产品交互不可见

问数工作流能够返回 `knowledge_matches`、`album_candidates` 和 `clarifying_questions`，但候选内容更多以 artifact 或折叠技术详情展示。

用户真正需要的是：

- 表名、中文注释、项目、分层、业务域；
- 为什么推荐；
- 可点击选择；
- 分页或继续缩小范围；
- 选择之后的下一步动作。

如果页面只显示“请选择一张表”，却没有显眼地展示表列表，产品上就等同于卡住。

### 3.3 资源标识符没有端到端保持

`giikin_aliyun.tb_dwd_ord_order_detail_di` 是一个完整资源标识符。系统必须从候选生成、前端选择、API 请求、会话状态、SQL 规划到执行全过程保持完整值。

不能在后续轮次重新从自然语言中提取，并退化为：

```text
tb_dwd_ord_order_detail_di
```

标识符应来自结构化候选项，而不是重新解析显示文本。

### 3.4 工作流执行和对话编排耦合不清

目前 `ChatAgent.chat()` 同时承担：

- 保存消息；
- 恢复上下文；
- 解析意图；
- 合并参数；
- 判断工作流；
- 执行服务；
- 保存结果。

后续继续增加 LLM、MCP、Skill 和多智能体路由时，这种入口式堆叠会让每一轮都像一次新请求。需要在 ChatAgent 与具体 WorkflowService 之间增加明确的会话协调层。

## 4. 设计原则

### 4.1 状态优先，历史辅助

- 工作流状态用于确定“现在做到哪一步”。
- 对话历史用于理解指代、语气和补充说明。
- 结构化答案优先于自然语言重新解析。
- 如果同时存在结构化选择和文本，结构化选择是事实来源。

### 4.2 确定性优先，LLM 增强

优先级如下：

1. 待处理的结构化交互回答；
2. 明确的资源 ID、表名、节点 ID；
3. 规则和已验证的业务合同；
4. 元数据搜索和候选排名；
5. LLM 意图理解、语义消歧和自然语言生成；
6. 信息不足时主动澄清，不猜测生产口径。

### 4.3 对话与执行分离

- Conversation Coordinator 决定当前轮次属于新目标、补充信息、候选选择、确认还是取消。
- Workflow Service 负责具体业务计划和执行。
- Executor 只接收经过校验的结构化参数。
- Verifier 判断结果是否真的完成。
- Response Builder 把状态转换为自然语言、卡片和进度事件。

### 4.4 默认安全

- 搜表、查元数据、生成只读 SQL 可以自动进行。
- 真实查询必须保持只读、限行和超时约束。
- 修改已有 dev 节点需要确认。
- 删除节点需要确认。
- 生产发布必须进入 Publish Gate，由人工批准。

## 5. 目标架构

```text
┌───────────────────────────────────────────────────────────────┐
│ Vue Conversation UI                                           │
│ 消息 / 候选卡片 / 参数表单 / 确认按钮 / 执行进度 / 结果表格    │
└──────────────────────────────┬────────────────────────────────┘
                               │ ChatRequest / InteractionAnswer
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ Conversation Coordinator                                      │
│ 1. 恢复会话状态                                               │
│ 2. 判断新目标或回答 pending interaction                       │
│ 3. 合并结构化槽位                                             │
│ 4. 决定 resume point                                          │
└───────────────┬───────────────────────────┬───────────────────┘
                │                           │
                ▼                           ▼
┌───────────────────────────┐   ┌───────────────────────────────┐
│ Context Assembly Layer    │   │ Intent / Workflow Router      │
│ Metadata / History        │   │ deterministic first           │
│ Project / Capabilities    │   │ LLM-assisted when ambiguous   │
└───────────────┬───────────┘   └───────────────┬───────────────┘
                └───────────────────────┬───────┘
                                        ▼
┌───────────────────────────────────────────────────────────────┐
│ Resumable Workflow Graph                                      │
│ UNDERSTAND → DISCOVER → CLARIFY → PLAN → CONFIRM              │
│            → EXECUTE → VERIFY → RESULT / BLOCKED              │
└──────────────────────────────┬────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ Existing Services                                             │
│ AgentWorkflowService / MetadataProvider / BFF / OpenAPI       │
│ MaxCompute / MCP / Skill / Modeling Engine / Publish Gate     │
└───────────────────────────────────────────────────────────────┘
```

### 5.1 Conversation Coordinator

建议新增一个薄协调层，不重写现有 WorkflowService：

```python
class ConversationCoordinator:
    async def handle(self, request: ChatRequest) -> ChatResponse:
        state = await self.state_store.load(request.conversation_id)

        if request.interaction_response:
            transition = self.interaction_resolver.resolve(
                state.pending_interaction,
                request.interaction_response,
            )
        else:
            transition = await self.intent_router.resolve(request.message, state)

        state = self.state_reducer.apply(state, transition)
        result = await self.workflow_runner.resume(state)
        return self.response_builder.build(state, result)
```

该层只负责状态转换和工作流恢复，不复制问数、建模或诊断业务逻辑。

### 5.2 Context Assembly Layer

保留现有文档提出的 Provider 思路，但明确用途：

| Provider | 提供内容 | 使用场景 |
|---|---|---|
| MetadataProvider | 表、字段、分区、专辑、引用热度 | 搜表、语义消歧、查询计划 |
| HistoryProvider | 最近消息、最近资源、历史摘要 | “刚才那张表”“继续上一步” |
| ProjectProvider | dev/prod 项目、schema、区域、目录约束 | 建模和发布参数 |
| CapabilityProvider | 当前可用工具、权限和健康状态 | 避免规划不可执行动作 |
| PreferenceProvider | 用户常用项目、层级、展示偏好 | 可选增强，不作为生产口径 |
| TerminologyProvider | 行业黑话→标准术语映射（"跑数"→"查询数据"，"口径"→"筛选条件"） | 消歧、改写用户输入 |
| TableConstraintProvider | 每张表的默认查询条件（DWD 表默认带 ds=昨天，ODS 表默认带分区） | 规则补充阶段注入 |

上下文必须按需装配，不能把所有元数据和全部历史直接塞给模型。

### 5.3 LLM 的职责边界

LLM 适合：

- 判断自然语言目标；
- 识别业务关键词和指代；
- 在多个相似候选间生成更自然的追问；
- 把结构化计划和执行结果解释给用户；
- 摘要较长历史。

LLM 不负责：

- 生成或恢复候选项 ID；
- 保存工作流阶段；
- 决定是否绕过确认或 Publish Gate；
- 修改完整表名、节点 ID、项目名；
- 在没有证据时猜生产指标口径；
- 直接声明任务成功。

## 6. 会话状态模型

### 6.1 ConversationState

```python
class ConversationState(TypedDict, total=False):
    conversation_id: str
    version: int

    objective: str
    active_workflow: str
    phase: str

    slots: dict[str, Any]
    selected_resources: dict[str, Any]
    candidate_sets: dict[str, list[dict[str, Any]]]

    pending_interaction: dict[str, Any] | None
    resume_point: str | None

    workflow_state: dict[str, Any]
    last_result: dict[str, Any]
    history_summary: str

    context_turn_count: int        # 当前连续对话轮数
    context_token_estimate: int    # 估算 token 占用
    last_context_summary_at: str   # 上次摘要时间
    context_overflow_strategy: str # "summarize" | "truncate" | "reset"

    created_at: str
    updated_at: str
```

字段说明：

- `objective`：本轮任务的根目标，例如“查订单表”。
- `active_workflow`：`ask_data`、`forward_modeling`、`diagnose_issue` 等。
- `phase`：当前工作流阶段。
- `slots`：已确认参数，例如层级、时间范围、粒度。
- `selected_resources`：完整表名、节点 ID、数据源 ID 等稳定资源。
- `candidate_sets`：当前轮候选快照，避免下一轮重新搜索后排序变化。
- `pending_interaction`：正在等待用户回答的问题。
- `resume_point`：回答后恢复的工作流节点。
- `workflow_state`：现有步骤、产物和执行状态。
- `last_result`：最近一次可供追问的结果摘要。

### 6.2 PendingInteraction

```json
{
  "interaction_id": "int_select_order_table_01",
  "type": "select_one",
  "slot": "table_name",
  "prompt": "请选择要查询的订单表",
  "options": [
    {
      "id": "table_01",
      "label": "订单详情全量表",
      "value": "giikin_aliyun.tb_dwd_ord_order_detail_di",
      "metadata": {
        "layer": "dwd",
        "project": "giikin_aliyun",
        "comment": "订单域-订单详情全量表"
      }
    }
  ],
  "allow_custom_input": true,
  "resume_action": "ask_data.preview_options"
}
```

支持的交互类型：

- `select_one`
- `select_many`
- `provide_text`
- `provide_parameters`
- `confirm`
- `approve_publish`
- `choose_next_action`

### 6.3 状态转换

```text
IDLE
  └─ 新消息 → UNDERSTAND

UNDERSTAND
  ├─ 参数充足且无歧义 → PLAN
  ├─ 需要搜索 → DISCOVER
  ├─ 存在歧义 → DISAMBIGUATE
  └─ 意图不清 → CLARIFY

DISAMBIGUATE  （歧义消解，参考去哪儿网意图确认 Agent）
  ├─ LLM 判断存在多种合理理解时，向用户列出候选含义并请求确认
  ├─ 收到确认 → resume_point
  ├─ 无法消解 → CLARIFY
  └─ 用户明确指定 → PLAN
  典型场景："查询昨天积分第二名的代理商"→ 按代理商汇总积分排序 vs 单笔积分排序

DISCOVER
  ├─ 单一强命中 → PLAN 或 CONFIRM
  ├─ 多候选 → CLARIFY
  └─ 无命中 → CLARIFY

CLARIFY
  ├─ 收到结构化回答 → MERGE → resume_point
  ├─ 收到文本回答 → 结合 pending_interaction 解析
  ├─ 取消 → CANCELLED
  └─ 新任务 → 重置后进入 UNDERSTAND

PLAN
  ├─ 只读安全操作 → EXECUTE
  ├─ 需确认操作 → CONFIRM
  └─ 只规划模式 → RESULT

EXECUTE → VERIFY → RESULT / BLOCKED
```

## 7. API 交互协议

### 7.1 请求

保留现有字段并增加结构化回答，保证向后兼容：

```json
{
  "message": "第一张",
  "conversation_id": "conv_123",
  "execution_mode": "auto",
  "initialize_data": false,
  "publish": false,
  "interaction_response": {
    "interaction_id": "int_select_order_table_01",
    "option_id": "table_01",
    "value": "giikin_aliyun.tb_dwd_ord_order_detail_di"
  },
  "context_updates": {
    "params": {
      "table_name": "giikin_aliyun.tb_dwd_ord_order_detail_di"
    }
  }
}
```

兼容规则：

- 老客户端只发送 `message` 时仍可工作。
- 如果会话存在 `pending_interaction`，文本优先按该问题解析，而不是重新识别整个任务。
- 如果同时发送 `interaction_response` 和文本，以结构化回答为准，文本作为备注。
- `interaction_id` 不匹配或已过期时，返回可恢复提示，不能静默应用到其他问题。

### 7.2 响应

```json
{
  "message": "已找到 13 张 DWD 订单表，请选择一张。",
  "success": true,
  "data": {
    "conversation": {
      "id": "conv_123",
      "workflow": "ask_data",
      "phase": "clarify",
      "resume_point": "ask_data.select_table"
    },
    "interaction": {
      "interaction_id": "int_select_order_table_01",
      "type": "select_one",
      "slot": "table_name",
      "prompt": "请选择目标表",
      "options": []
    },
    "progress": {
      "completed": ["understand", "discover"],
      "current": "clarify",
      "pending": ["plan", "execute", "verify"]
    },
    "artifacts": [],
    "next_actions": []
  }
}
```

### 7.3 标识符规则

- 表必须保存完整 `project.table`。
- DataWorks 节点必须保存稳定节点 ID，不以展示名称替代。
- 候选项使用独立 `option_id`，显示文案和实际值分离。
- 前端不得把 label 直接当执行参数。
- SQL 规划前再次验证项目、表名和只读约束。

## 8. “查订单表”标准对话流程

### 8.1 第一步：理解和发现

输入：

```text
查订单表
```

系统行为：

1. 确定为 `ask_data` 下的 `search_table` 子目标。
2. 提取业务关键词“订单”，而不是错误截取为“单”。
3. 调用 MetadataProvider 搜索候选。
4. 根据数据专辑命中、项目、分层、引用热度和名称相关度排名。
5. 候选过多时先按层级或业务域聚合。

响应应包含层级卡片，而不是一次输出几十张表的 JSON。

### 8.2 第二步：缩小范围

用户选择 `DWD` 后：

- 保存 `slots.layer = "dwd"`；
- 从上一轮候选快照过滤，不必重新开始整个意图识别；
- 返回最多 8～10 张表卡片；
- 支持“查看更多”“换业务域”“直接输入完整表名”。

### 8.3 第三步：选择资源

用户点击目标表后：

```json
{
  "table_name": "giikin_aliyun.tb_dwd_ord_order_detail_di"
}
```

系统将该值写入 `selected_resources.table`，后续不再从自然语言中提取。

### 8.4 第四步：选择动作

选表不等于默认执行 `SELECT *`。Agent 应询问或提供快捷动作：

- 预览数据；
- 查看字段；
- 查看最新分区；
- 查询数据量；
- 查看血缘；
- 生成自定义只读查询。

如果用户原始目标已经明确包含动作，例如“查订单表有多少条”，则可以直接规划计数查询，不必再次追问动作。

### 8.5 第五步：执行和验收

执行只读查询时：

1. 显示正在使用的表和查询目标；
2. 生成只读、限行 SQL；
3. 展示查询通道状态；
4. Cookie/BFF 失败时按现有策略切换 AK/SK；
5. 返回列、行、耗时、通道和校验状态；
6. 失败时保留已选择的表和查询计划，允许用户修复权限后重试。

## 9. 前端交互设计

### 9.1 消息不是唯一载体

对话区需要支持以下内容块：

- 普通消息；
- 思考和执行状态；
- 候选表卡片；
- 参数补充表单；
- 确认卡片；
- 查询结果表格；
- SQL/DDL 产物；
- Publish Gate 审批卡片；
- 错误恢复和重试动作。

### 9.2 候选表卡片

每张候选卡至少展示：

- 中文注释或业务名称；
- 完整 `project.table`；
- 数据层级；
- 业务域/专辑；
- 推荐原因；
- 最近使用或引用热度（如果可用）；
- “选择”按钮。

候选表不能只放在“查看技术详情”的折叠区域中。

### 9.3 澄清问题

澄清问题应明确说明回答方式：

```text
请选择一张目标表（可点击候选，也可以输入完整 project.table）。
```

不能把问题文本本身做成按钮，让用户点击后只是把问题复制进输入框。

### 9.4 等待感知

首个可见反馈应尽快出现：

```text
正在理解目标 → 正在搜索元数据 → 找到 32 张候选 → 等待选择
```

SSE 应发送真实阶段事件，而不是连接后只显示一个统一的“思考中”。建议事件：

- `conversation.started`
- `intent.resolved`
- `metadata.search.started`
- `metadata.search.completed`
- `interaction.required`
- `workflow.resumed`
- `execution.started`
- `execution.channel_changed`
- `verification.completed`
- `response.completed`

## 10. 上下文与 Token 预算

上下文按任务需要装配，预算不绑定某个具体模型：

| 上下文 | 建议预算 | 策略 |
|---|---:|---|
| 系统规则与安全边界 | 600～1000 tokens | 固定、版本化 |
| 当前 ConversationState | 300～600 tokens | 结构化摘要 |
| 最近对话 | 800～1500 tokens | 最近 6～10 轮，旧历史摘要 |
| 元数据候选 | 1000～2500 tokens | 最多 20 条，优先注释和关键字段 |
| 项目和能力状态 | 300～600 tokens | 只注入当前任务相关能力 |
| 当前用户输入 | 原文 | 不改写事实标识符 |

注意：候选项的真实值保存在状态和 API 结构中，不依赖上下文窗口长期记忆。

## 11. 失败处理与恢复

### 11.1 搜表无结果

返回可执行建议：

- 换更具体的业务关键词；
- 输入完整英文表名；
- 选择项目或业务域；
- 检查 Cookie/BFF 元数据权限。

保留当前 objective，不要求用户从头描述。

### 11.2 多候选

- 先按层级、项目或业务域聚合；
- 保存候选快照；
- 用户回答“第一张”“DWD”“订单详情”时，以 pending interaction 为语境解析。

### 11.3 查询通道失败

返回：

- 已选择的完整表；
- 已生成 SQL；
- Cookie/BFF 与 AK/SK 各自的简短错误；
- 可点击的“刷新 Cookie 后重试”“检查 MaxCompute 权限”“仅保留 SQL”。

不得丢失已完成的选表和规划状态。

### 11.4 新任务、取消和回退

支持明确指令：

- `取消`：终止当前 pending interaction，保留历史。
- `重新开始`：清空当前工作流状态，保留会话消息。
- `换个任务`：创建新 objective。
- `返回上一步`：回到上一个可恢复 checkpoint。

## 12. 持久化设计

建议区分三类数据：

| 数据 | 存储 | 用途 |
|---|---|---|
| 对话消息 | `conversation_history` | 页面历史、LLM 上下文 |
| 会话状态 | LangGraph checkpoint / SQLite | 工作流恢复 |
| 待交互与候选快照 | 会话状态或独立 interaction 表 | 精确回答和审计 |

如果引入独立表，可使用：

```text
conversation_interactions
- interaction_id
- conversation_id
- interaction_type
- slot
- prompt
- options_json
- status: pending / answered / cancelled / expired
- answer_json
- resume_action
- created_at
- answered_at
```

所有状态更新应带 `version`，避免同一会话并发请求相互覆盖。

## 13. 实施阶段

### Phase 0：修复当前确定性断点

目标：先让现有“查订单表”链路可靠闭环（保持现有架构，不拆分 Agent）。

1. 完整保留 `project.table`。
2. 修复中文“订单表”实体截取异常。
3. 将 `conversation_id` 明确传入需要 HistoryProvider 的工作流参数。
4. 确保异步 ConversationGraph 初始化全部正确 `await`。
5. 增加真实三轮回归：`查订单表 → 只要 dwd → 选择完整表名`。

### Phase 1：结构化交互协议

1. 扩展 ConversationState。
2. 定义 `PendingInteraction` 和 `InteractionResponse`。
3. 在 `/agent/chat` 中支持结构化回答。
4. 实现 ConversationCoordinator 薄协调层和状态 reducer。
5. 保持纯文本请求向后兼容。

### Phase 2：候选卡片 + 歧义消解（最小可用闭环）

1. 后端把候选转换为统一 options 协议。
2. 前端新增候选表卡片和层级筛选。
3. 选择操作发送 `option_id + value`，不发送显示文案代替真实值。
4. 增加“预览、字段、分区、血缘、SQL”快捷动作。
5. 实现 DISAMBIGUATE 状态：LLM 检测歧义 → 列出候选含义 → 用户确认。

### Phase 3：上下文管理 + 术语库（去噪）

1. 统一 MetadataProvider、HistoryProvider、ProjectProvider、CapabilityProvider。
2. 新增 TerminologyProvider（行业黑话映射）和 TableConstraintProvider（默认查询条件）。
3. 实现上下文生命周期管理：连续 10 轮未开新会话 → 自动摘要；token 估算超 8000 → 强制摘要。
4. 对确定性规则无法处理的表达调用 LLM，使用结构化输出。
5. 配置超时、降级和可观测日志。

### Phase 4：真实 Streaming 和恢复

1. SSE 输出真实阶段事件（conversation.started → intent.resolved → metadata.search → interaction.required → ...）。
2. 长查询显示通道切换和耗时。
3. 页面刷新后恢复 pending interaction、进度和结果。
4. 支持失败后从 checkpoint 重试。

### Phase 5：RAG 反馈闭环 + 评测驱动

1. 用户点赞/点踩 → 正确结果沉淀到 RAG QA 库 → 后续类似问题召回参考。
2. 评测 Agent 定时跑 Case 集，生成准确率报告。
3. Case 集来源：从 DataWorks 平台反向获取历史实际执行 SQL，业务方补充自然语言问题。
4. 按知识缺失 / Agent 逻辑 / 数据问题分类，驱动迭代。

### Phase 6：扩展到其他工作流

将同一交互协议复用到：

- ODS/DWD/全链路建模的参数补充；
- 调度粒度、目录、逻辑主键确认；
- 异常诊断中的节点选择；
- 修改已有节点确认；
- Publish Gate 审批。

## 14. 代码影响范围

建议优先复用和小步改造：

| 文件/模块 | 改造方向 |
|---|---|
| `dataworks_agent/agent/core.py` | 将状态协调职责逐步下沉到 Coordinator |
| `dataworks_agent/agent/conversation_graph.py` | 扩展会话状态、pending interaction 和 resume point |
| `dataworks_agent/routers/agent.py` | 增加结构化回答协议并保持兼容 |
| `dataworks_agent/routers/agent_sse.py` | 输出真实阶段事件 |
| `dataworks_agent/agent/workflow_service.py` | 接收已确认槽位，返回统一 interaction，不重写业务执行 |
| `dataworks_agent/agent/context/*` | 统一按需上下文装配 |
| `dataworks_agent/agent/nlu/entity_extractor.py` | 保持完整资源标识符 |
| `frontend/src/components/agent/AgentChat.vue` | 候选、确认、恢复和结果交互 |
| `frontend/src/components/agent/chatInteraction.ts` | 请求/响应类型和 interaction payload |
| `tests/unit/test_agent_router.py` | API 兼容和结构化回答测试 |
| `tests/unit/test_agent_workflow_service.py` | 工作流恢复测试 |
| 前端交互测试 | 卡片选择、刷新恢复、错误重试 |

不要为了对话式能力复制一套新的问数、建模或发布服务。

## 15. 验收场景

### 15.1 查订单表

```text
查订单表
→ 返回层级选项和候选摘要
→ 只要 dwd
→ 返回 DWD 候选卡片
→ 选择 giikin_aliyun.tb_dwd_ord_order_detail_di
→ 完整表名保持不变
→ 选择预览数据
→ 返回真实只读结果或可恢复的权限错误
```

### 15.2 指代上一资源

```text
查 ods_user 的字段
→ 返回字段
→ 刚才那个表有多少条
→ 自动使用上一轮完整表名
→ 生成 count 查询
```

### 15.3 建模补充参数

```text
帮我建一个 ODS 到 DWD 链路
→ 询问数据源和源表
→ 用户回答源表
→ 询问粒度和逻辑主键
→ 用户确认
→ 生成计划和产物
→ dev 写入前按边界确认，生产发布进入 Publish Gate
```

### 15.4 页面刷新恢复

```text
Agent 正在等待用户选表
→ 刷新页面
→ 恢复同一个 conversation_id
→ 仍显示原候选卡片和 pending interaction
```

### 15.5 话题切换

```text
当前正在选订单表
→ 用户说“换个任务，排查节点 123”
→ 当前交互取消
→ 新 objective 进入 diagnose_issue
→ 旧任务保留在历史中但不污染新参数
```

## 16. 成功指标

| 指标 | 目标 |
|---|---:|
| 模糊搜表进入有效候选的比例 | ≥ 90% |
| 用户选择后正确恢复工作流的比例 | ≥ 95% |
| 完整资源标识符保持率 | 100% |
| 多轮任务闭环成功率 | ≥ 80% |
| 首个状态反馈时间 | ≤ 500 ms |
| 普通元数据候选首轮响应 | ≤ 2 秒 |
| 页面刷新后的待交互恢复率 | 100% |
| 危险操作绕过确认次数 | 0 |
| 生产发布绕过 Publish Gate 次数 | 0 |

成功不能只统计接口返回 `success=true`，还必须由 Workflow Verifier 确认目标是否真正完成。

## 17. 测试策略

### 单元测试

- 状态 reducer；
- interaction answer 解析；
- 候选快照和 option ID；
- 完整 `project.table` 保持；
- 新任务、取消、回退；
- 旧文本协议兼容。

### 集成测试

- 三轮及以上连续对话；
- MetadataProvider 搜索到候选后的选择恢复；
- Cookie/BFF 与 AK/SK 通道回退；
- ConversationGraph 重启恢复；
- Publish Gate 确认。

### 页面测试

- 候选卡片真实可见、可点击；
- 选择后输入框和卡片状态更新；
- 长请求显示阶段进度；
- 失败后可直接重试；
- 刷新后恢复待选择状态；
- 桌面和窄屏布局可用。

## 20. 评测驱动迭代（参考去哪儿网经验）

### 20.1 Case 集管理

- 从 DataWorks 平台反向获取用户历史实际执行的 SQL（不要依赖"让业务方提供"，他们给的 Case 太简单、覆盖面不够）。
- 让业务方根据真实 SQL 补充对应的自然语言问题。
- 持续沉淀真实 Case，作为评测和 RAG 的基础数据。

### 20.2 自动评测

- 评测 Agent 定时对整个 Case 集进行评测。
- 生成准确率报告，按以下维度分类：
  - 知识缺失（术语未覆盖、表关系未知）
  - Agent 逻辑问题（意图识别错误、参数合并异常）
  - 数据问题（表结构变更、字段缺失）
- 开发人员根据报告决定补充知识库还是修复 Agent。

### 20.3 反馈闭环

- 用户可对查询结果点赞/点踩。
- 点赞触发事件，将正确问答沉淀到 RAG QA 知识库。
- 后续类似问题召回 Top-N 相似 QA 作为参考模板，提升生成稳定性。
- 点踩进入修复队列，纳入下一轮评测 Case。

### 20.4 上下文清理策略

去哪网的教训：用户几乎不会主动开新会话，历史上下文无限累积导致准确率下降。

- 连续 10 轮未开新会话 → 自动摘要旧历史，保留最近 3 轮原文。
- token 估算超过 8000 → 强制摘要。
- 用户说"重新开始"或"换个任务" → 清空 workflow_state，保留最近 3 轮。
- 追问 Agent 判断当前问题是"新问题"还是"上一个问题的追问"，避免无关历史干扰。

## 18. 非目标

本轮设计不追求：

- 让 LLM 自由决定所有工具调用和线上操作；
- 一次性重写 `AgentWorkflowService`；
- 用一个超大 Prompt 替代状态机；
- 自动发布生产任务；
- 将本地业务私有词和真实目录硬编码到通用产品；
- 只做聊天气泡美化而不解决工作流恢复。
- 不追求一次性拆分为 5+ Agent（先 Single Agent 跑通，根据实际问题再拆分）。
- 不追求 RAG 反馈闭环（先保证准确率，再做学习沉淀）。

## 19. 最终定义

对话式 Agent 的完成标准不是“用户可以连续发送消息”，而是：

> 用户用自然语言提出目标，Agent 能基于真实元数据发现资源；在信息不足时给出可操作的结构化澄清；用户回答后从正确节点恢复；执行过程可见、结果可验证、失败可继续、危险操作受审批约束。

上下文注入让 Agent 看得见，结构化交互让 Agent 问得清，状态机让 Agent 接得上，Workflow 与 Verifier 让 Agent 做得对。

## 14. 实施状态（2026-07-17）

本期已在 `codex/continuous-conversation` 分支完成以下闭环：

1. **结构化交互协议**：`/agent/chat` 和 `/agent/ws` 支持 `interaction_answer`，服务端用 `interaction_id + option_id + state_version` 解析选项，不信任前端回传的表名或目录路径。
2. **可恢复会话状态**：`ConversationGraph` 持久化 `selected_resources`、`pending_interaction`、`last_result` 和 `state_version`；页面刷新或进程重启后可恢复当前待回答问题。
3. **找表连续对话**：候选数超过 8 时先按 ODS/DWD/DWS/DMR 等分层，选择分层后继续过滤；候选数不超过 8 时直接返回精确表选项，并始终保留完整 `project.table`。
4. **选表后动作**：已提供查看字段、预览数据、查看分区、查看血缘、生成 ODS 节点、生成 DWD 节点和自定义回答。
5. **前端交互卡**：`MessageBubble.vue` 渲染当前有效的选项和自定义输入；旧交互保留展示但不可重复提交，请求失败时可解锁重试。
6. **节点安全落位**：测试环境仅使用已只读确认的广告报告目录 `00_ODS`、`02_DWD`、`03_DWS`、`04_DMR`；`01_DIM` 未被确认，因此必须阻断。生产环境仅保留通过 Cookie/DataStudio 在线只读证据确认的候选目录；无证据、证据过期或候选不唯一时停止。
7. **节点写入确认**：先返回节点名、父目录、完整路径、创建/更新模式和发布边界；用户确认后再次检查目录和同路径同名节点，写入开发草稿后回读校验。`CreateNode` 固定使用 `container_id=None` 和 `scene="DATAWORKS_PROJECT"`，不调用任何目录创建接口，不自动发布。

### 14.1 验证结果

- 后端集成测试：`133 passed`。
- Ruff：`uv run ruff check .` 通过。
- 前端单元测试：`38 passed`。
- TypeScript/Vite 生产构建：通过。
- 目录创建审计：本期改动路径中无 Folder/create-directory/createPackage 调用；节点创建只在新鲜、精确且为真的目录证据之后发生。

### 14.2 本期未执行的真实写入

本期只使用 mock 和只读证据验证，**没有创建真实 DataWorks 测试节点**，没有删除节点，没有发布生产。这符合“未经明确授权不做真实 DataWorks 写入测试”的项目约束。

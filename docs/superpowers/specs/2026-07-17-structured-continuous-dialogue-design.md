# 结构化连续对话与安全节点落位设计

## 1. 目标

在现有 DataWorks Agent 功能之上增加可恢复的连续澄清机制，不复制找表、问数、建模或节点执行服务。

首个完整闭环：

```text
找表 → 返回少量选项 + 自定义回答 → 继续筛选 → 精确选表
     → 选择后续动作 → 可选生成节点 → 确认后创建或更新节点
```

系统必须同时支持：

- 点击结构化选项；
- 直接输入自然语言作为当前问题的自定义回答；
- 页面刷新和服务重启后恢复当前待回答问题；
- 保持完整资源标识符，不把 `project.table` 重新交给 NLU 猜测；
- 测试环境将节点放入广告报告的既有目录；
- 生产环境动态查找既有目录，并永久禁止创建目录。

## 2. 非目标

本阶段不实现：

- Codex 式多任务侧栏、会话归档和跨用户同步；
- 全量重写为另一套 LangGraph Agent；
- 多选、拖拽、复杂动态表单；
- 自动生产发布；
- 任何 DataWorks 文件夹、业务流程或分层目录创建。

## 3. 现有能力复用

继续使用：

- `POST /agent/chat`；
- `conversation_id`；
- `ChatAgent` 与 `AgentWorkflowService`；
- 现有找表、问数、建模、血缘和节点执行能力；
- `ConversationGraph` 的 LangGraph SQLite checkpoint；
- `conversation_history`；
- `SmartChatPage.vue`、`MessageBubble.vue` 和 `chatInteraction.ts`；
- OpenAPI Node/FlowSpec 创建与更新链路；
- Cookie/DataStudio 元数据与目录树兜底链路；
- Publish Gate。

不新增第二套业务工作流。

## 4. 结构化交互协议

### 4.1 Interaction

后端在 `data.interaction` 返回当前待回答问题：

```json
{
  "interaction_id": "int_123",
  "type": "single_select",
  "purpose": "select_table",
  "prompt": "请选择目标表",
  "options": [
    {
      "id": "opt_1",
      "label": "订单详情全量表",
      "description": "DWD · 日分区",
      "value": "giikin_aliyun.tb_dwd_ord_order_detail_di"
    }
  ],
  "allow_custom_input": true,
  "custom_input_placeholder": "输入其他表名或进一步描述筛选条件",
  "status": "pending",
  "state_version": 3
}
```

第一期只实现：

- `single_select`；
- `confirm`；
- `free_text`。

每个交互都必须允许自定义回答；确认类交互可以将自定义回答解释为修改要求，而不是直接执行。

### 4.2 InteractionAnswer

点击选项时：

```json
{
  "conversation_id": "conv_123",
  "message": "订单详情全量表",
  "interaction_answer": {
    "interaction_id": "int_123",
    "option_id": "opt_1",
    "state_version": 3
  }
}
```

自定义回答时：

```json
{
  "conversation_id": "conv_123",
  "message": "只要包含退款金额字段的 DWD 表",
  "interaction_answer": {
    "interaction_id": "int_123",
    "custom_text": "只要包含退款金额字段的 DWD 表",
    "state_version": 3
  }
}
```

保留 `message` 字段以兼容现有历史、日志和 NLU。服务端优先处理 `interaction_answer`，并通过服务端 checkpoint 中保存的 option ID 映射解析真实值。前端回传的展示文字或 value 不能成为执行依据。

## 5. 会话状态

扩展现有 `ConversationState`：

```python
class ConversationState(TypedDict, total=False):
    objective: str
    action: str
    params: dict[str, Any]
    workflow_state: dict[str, Any]
    selected_resources: dict[str, Any]
    pending_interaction: dict[str, Any] | None
    last_result: dict[str, Any]
    state_version: int
```

职责：

- `objective`：当前根目标；
- `params`：已确认槽位；
- `selected_resources`：完整表名、节点 UUID 等确定性标识符；
- `pending_interaction`：唯一当前有效问题；
- `last_result`：用于“刚才那个表”等跟进；
- `state_version`：拒绝旧页面或重复点击提交的过期答案。

状态处理顺序：

```text
加载 checkpoint
→ 处理取消/重新开始/新任务
→ 验证 interaction_id + state_version
→ 应用选项或自定义回答
→ 更新已确认参数与资源
→ 调用现有工作流
→ 产生下一 interaction 或完成目标
→ 保存 checkpoint 和历史快照
```

有待回答交互但请求未携带 `interaction_answer` 时：

1. `取消`、`重新开始` 清除当前交互；
2. `换个任务...` 结束旧目标并进入新意图；
3. 其他普通文本视为当前交互的自定义回答；
4. 没有待回答交互时才走普通意图识别。

## 6. 找表状态流

```text
DiscoverTables
├─ 候选 > 8 → SelectLayer
├─ 候选 1..8 → SelectTable
└─ 候选 0 → NoResult

SelectLayer
├─ 选择 ODS/DWD/DWS/... → SelectTable
└─ 自定义条件 → 重新筛选

SelectTable
├─ 选择具体表 → SelectAction
└─ 自定义条件 → 保留根目标继续缩小候选

SelectAction
├─ 查看字段/分区/血缘/预览 → 现有只读能力
├─ 生成节点 → NodePlacement
└─ 自定义回答 → 使用已选表继续理解
```

候选规则：

- 超过 8 张时先按数据层分组；
- 每轮最多展示 8 个主要选项；
- 始终提供自定义回答；
- option ID 稳定绑定完整 `project.table`；
- 完整表名一旦确认，后续不得截断为裸表名。

## 7. 前端交互与恢复

### 7.1 组件

- `chatInteraction.ts`：统一请求、响应、Interaction 和 InteractionAnswer 类型；
- `MessageBubble.vue`：展示选项、自定义回答、已选择、过期和重试状态；
- `SmartChatPage.vue`：发送结构化回答并恢复 active interaction；
- `AgentChat.vue`：保持协议兼容，避免第二聊天入口失效。

### 7.2 行为

- 点击后立即锁定，防止重复提交；
- 请求失败解除锁定并允许重试；
- 请求成功后旧选项可见但不可再次操作；
- 自定义回答支持 Enter 提交、Shift+Enter 换行；
- 只有 checkpoint 指定的当前交互可操作；
- 过期提交返回 `interaction_expired` 和当前有效交互，不返回 500。

### 7.3 历史恢复

`GET /agent/messages` 兼容扩展：

```json
{
  "messages": [],
  "active_interaction": {},
  "state_version": 3
}
```

`conversation_history` 增加结构化 payload 字段。职责划分：

- checkpoint 是当前可执行状态的唯一来源；
- 历史 payload 是不可变展示快照；
- `content` 只保存可读正文，不再存放需要前端直接显示的 JSON envelope；
- 旧记录没有 payload 时继续按普通文本展示。

## 8. 节点创建连续对话

选表后可以返回：

```text
[查看字段] [预览数据] [查看分区] [查看血缘]
[生成 ODS 节点] [生成 DWD 节点] [自定义回答]
```

生成节点必须先返回确认交互，展示：

- 节点名称；
- 完整目标目录；
- 完整节点路径；
- 创建还是更新；
- 脚本/调度摘要；
- 不创建目录；
- 不自动发布生产。

用户确认后才允许进入真实写入。

## 9. 测试环境节点落位策略

测试节点固定使用已通过真实 DataStudio 目录树只读确认的广告报告目录：

```text
业务流程/106_广告报告/MaxCompute/数据开发/00_ODS
业务流程/106_广告报告/MaxCompute/数据开发/02_DWD
业务流程/106_广告报告/MaxCompute/数据开发/03_DWS
业务流程/106_广告报告/MaxCompute/数据开发/04_DMR
```

映射：

```python
TEST_AD_REPORT_DIRECTORIES = {
    "ODS": "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS",
    "DWD": "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD",
    "DWS": "业务流程/106_广告报告/MaxCompute/数据开发/03_DWS",
    "DMR": "业务流程/106_广告报告/MaxCompute/数据开发/04_DMR",
}
```

测试目录树未确认存在 `01_DIM`。测试请求 DIM 节点时必须停止并返回待确认，不能创建目录或改放其他层级。

测试环境也不需要创建目录；它只允许在上述既有目录中创建可清理的测试节点。

## 10. 生产环境节点落位策略

生产环境不硬编码 `106_广告报告`。根据业务域、分层、节点类型和用户已确认信息，只读查找真实已有目录。

```text
找到唯一且精确匹配的父目录
→ 展示路径并要求用户确认
→ 精确查询同路径同名节点
→ 存在则更新 UUID，不存在才创建节点

找到多个候选目录
→ 返回目录选项 + 自定义回答
→ 不执行写入

没有候选或无法确认
→ 停止并返回待确认
→ 不使用默认目录
→ 不创建目录
```

生产环境始终禁止：

- 创建业务流程；
- 创建文件夹或分层目录；
- 通过 Cookie/BFF、OpenAPI、FlowSpec、createPackage 或其他接口间接创建目录；
- 路径不完整时回退默认目录；
- 把自定义文本路径未经目录树精确匹配直接用于写入。

## 11. 目录确认与节点写入

### 11.1 目录确认

目录候选可以来自配置和语义映射，但真实写入前必须获得在线只读证据：

1. Cookie/DataStudio 目录树：主要来源，可确认空目录；
2. OpenAPI `ListNodes` 的 `Script.Path`：辅助来源，只能证明已有节点目录；
3. 文档或常量：仅用于生成候选，不能单独授权写入。

本次只读核实发现 OpenAPI 扫描到的节点中没有 `106_广告报告` 路径，因此不能用“没有节点”推断“目录不存在”。

目录证据仅对当前写入请求有效，不永久缓存为可信事实。

### 11.2 节点精确复用

创建或更新前：

1. 规范化完整节点路径；
2. 精确查询同路径同名节点；
3. 已存在则复用 UUID 并更新；
4. 不存在且父目录已确认时才创建；
5. 不允许模糊名称匹配决定更新对象。

### 11.3 OpenAPI 创建

节点创建使用：

```python
create_node(
    spec=flowspec,
    container_id=None,
    scene="DATAWORKS_PROJECT",
)
```

节点位置仅由 `spec.nodes[0].script.path` 决定。不得传文件夹 UUID 作为 container ID。

创建后必须重新读取并验证：

- 节点 UUID；
- `Script.Path` 完全一致；
- 节点名称、语言和运行命令一致；
- 脚本内容一致；
- 节点处于开发草稿状态；
- 未自动发布；
- 没有产生任何新目录。

生产发布仍必须经过 Publish Gate。

## 12. 失败与恢复

- 过期交互：返回当前有效 interaction；
- 无表候选：允许修改关键词或取消；
- 多表候选：继续结构化筛选；
- 完整表名丢失：视为验证失败，不执行查询或节点写入；
- 目录不存在或无法确认：停止，不创建目录；
- 同路径同名节点查询失败：停止，不创建重复节点；
- 节点创建后回读不一致：标记失败并返回 UUID/路径供修复；
- 用户切换任务：取消旧 pending interaction，旧参数不污染新目标；
- 页面刷新：恢复当前交互；
- 服务重启：从 SQLite checkpoint 恢复。

## 13. 代码影响范围

后端：

- `dataworks_agent/routers/agent.py`
- `dataworks_agent/agent/core.py`
- `dataworks_agent/agent/conversation_graph.py`
- `dataworks_agent/agent/workflow_service.py`
- `dataworks_agent/agent/interaction.py`（新增小型协议与 reducer）
- `dataworks_agent/db/models.py`
- `dataworks_agent/api_clients/openapi_node_adapter.py`
- Cookie/DataStudio 目录树只读解析入口

前端：

- `frontend/src/components/agent/chatInteraction.ts`
- `frontend/src/components/agent/MessageBubble.vue`
- `frontend/src/pages/SmartChatPage.vue`
- `frontend/src/components/agent/AgentChat.vue`

测试：

- `tests/integration/test_agent_api.py`
- `tests/integration/test_agent_integration.py`
- `frontend/src/__tests__/agentChatInteraction.spec.ts`
- 新增必要的前端交互测试文件

## 14. 验收场景

### 14.1 点击选项

```text
找订单表
→ 返回数据层选项 + 自定义回答
→ 点击 DWD
→ 返回 DWD 表候选
→ 点击具体表
→ 完整 project.table 被保存
→ 点击查看字段
→ 正确调用现有只读能力
```

### 14.2 自定义回答

```text
找订单表
→ 只要 DWD
→ 要包含退款金额字段
→ 第一个
→ 查最新分区有多少条
```

每轮都必须保留根目标和完整表标识符。

### 14.3 刷新恢复

```text
等待用户选表
→ 刷新页面
→ 恢复相同候选和自定义输入
→ 继续完成工作流
```

### 14.4 过期选项

旧 interaction 被新筛选替代后，点击旧选项返回 `interaction_expired`，不得执行旧目标。

### 14.5 测试节点创建

```text
选择生成 DWD 节点
→ 目标目录固定为广告报告 02_DWD
→ 目录只读确认
→ 同路径同名查询
→ 用户确认
→ 创建或更新测试节点
→ 回读验证
→ 不创建目录、不发布生产
```

### 14.6 生产目录歧义

```text
生产请求生成 DWD 节点
→ 找到多个已有目录
→ 返回目录选项 + 自定义回答
→ 未确认前不写入
```

### 14.7 生产目录缺失

```text
生产目标目录不存在
→ 返回 blocked/needs_context
→ 不回退默认目录
→ 不创建目录
```

## 15. 验证

后端：

```powershell
uv run python -m pytest tests/integration/ -q --tb=short
uv run ruff check .
```

前端：

```powershell
Set-Location frontend
npm run test:unit
npm run build
```

真实 DataWorks 验证分两级：

1. 默认使用 mock、只读目录探针和现有节点；
2. 真实创建测试节点仅使用广告报告既有目录，执行前再次确认路径，创建后回读，绝不创建目录或发布生产。

## 16. 实施顺序

1. 修复并扩展 ConversationGraph 状态与持久化；
2. 增加 Interaction/InteractionAnswer 协议和兼容 API；
3. 将现有找表候选适配为 interaction；
4. 完成前端选项、自定义回答和刷新恢复；
5. 接入节点生成确认交互；
6. 实现测试/生产 NodePlacementPolicy 和目录只读确认；
7. 接入精确复用、创建后回读和 Publish Gate；
8. 完成集成测试、前端测试和真实只读/测试节点验证。

# 对话式交互改造方案

> 项目: dataworks-agent 智能数仓建模系统
> 版本: v2.0
> 日期: 2026-07-17
> 状态: 方案设计（聚焦上下文注入）

## 1. 问题定义

### 1.1 核心问题：模型拿不到上下文

当前系统最大的问题不是 Streaming，而是 **LLM 在做决策时缺少关键上下文**。

```
用户: "查订单表"
    ↓
LLMIntentClassifier 只拿到 raw_text = "查订单表"
    ↓
LLM 不知道:
  - 数据仓库里有哪些表？
  - 用户之前聊过什么？
  - 当前有哪些业务域？
  - 可用的工具有哪些？
    ↓
返回 unknown, confidence=0.0
    ↓
走 dry-run 路径，用户看到空洞的 proposal
```

**一句话：模型没有"眼睛"，只能瞎猜。**

### 1.2 上下文断裂点分析

| 断裂点 | 现状 | 应该是什么 |
|--------|------|-----------|
| 元数据 | LLM 不知道有哪些表 | LLM 能搜索到匹配的表列表 |
| 对话历史 | 只存 params/action/workflow_state | LLM 能看到完整的多轮对话内容 |
| 项目结构 | LLM 不知道目录树/业务域 | LLM 知道当前项目的组织结构 |
| 工具能力 | LLM 不知道能调什么 | LLM 能看到工具列表和参数签名 |
| 用户偏好 | 完全没有 | LLM 知道用户是谁、常用什么表 |

### 1.3 目标状态

```
用户: "查订单表"

System Prompt 组装:
  ┌─ 对话历史: 上一轮讨论了 ods_user, 用户是电商团队
  ├─ 元数据: 搜索到 3 张订单相关表
  ├─ 可用工具: search_table, query_lineage, create_node, ...
  └─ 项目结构: 业务流程目录

LLM 输出:
  action: "search_and_query"
  params: {keyword: "order", candidates: ["cda.order_detail", ...]}
  response: "找到以下订单表，你想查哪张？"

用户: "第一张"
    ↓
上下文更新 + 表结构查询 → 返回结果
```

## 2. 架构设计

### 2.1 核心：上下文注入层 (Context Assembly Layer)

```
┌─────────────────────────────────────────────────────────┐
│                  Context Assembly Layer                  │
│                                                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐          │
│  │ Metadata  │  │ History   │  │ Project   │          │
│  │ Provider  │  │ Provider  │  │ Provider  │          │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘          │
│        │              │              │                  │
│        ▼              ▼              ▼                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │           Prompt Assembler                       │   │
│  │  System Prompt + Context + User Message           │   │
│  └─────────────────────┬───────────────────────────┘   │
│                        │                                │
│  ┌─────────────────────▼───────────────────────────┐   │
│  │           Tool Registry (MCP)                    │   │
│  │  可用工具列表 + 参数签名 + 示例                    │   │
│  └─────────────────────┬───────────────────────────┘   │
└────────────────────────┼───────────────────────────────┘
                         │
                         ▼
              ┌──────────────────┐
              │   LLM (DeepSeek) │
              │   完整上下文输入   │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  Structured Output│
              │  action + params  │
              │  + response text  │
              └──────────────────┘
```

### 2.2 三大上下文 Provider

#### Provider 1: MetadataProvider — 元数据上下文

LLM 决策时必须知道数据仓库里有什么。

```python
# dataworks_agent/agent/context/metadata_provider.py

class MetadataProvider:
    """为 LLM 提供元数据上下文"""

    async def assemble(self, message: str, context: dict) -> str:
        """根据用户消息，预搜索相关元数据，注入到 prompt"""

        # 1. 从用户消息中提取可能的表名/关键词
        keywords = self._extract_keywords(message)

        # 2. 搜索匹配的表 (复用 bff.search_tables)
        tables = []
        for kw in keywords:
            hits = await self._search_tables(kw)
            tables.extend(hits)

        # 3. 去重、排序、截断 (避免 token 爆炸)
        tables = self._dedup_and_limit(tables, max_tables=20)

        # 4. 格式化为 LLM 可读的上下文
        return self._format_metadata_context(tables, context)

    def _format_metadata_context(self, tables: list, context: dict) -> str:
        """生成元数据上下文段落"""
        if not tables:
            return "（未找到匹配的表，请用户明确表名）"

        lines = ["## 当前数据仓库中匹配的表:"]
        for t in tables:
            lines.append(
                f"- {t['name']} ({t.get('layer', '?')}层, "
                f"{t.get('domain', '未分类')}, "
                f"字段数: {t.get('column_count', '?')})"
            )
        return "\n".join(lines)
```

**关键设计：按需搜索，不是全量灌入。** 用户说"查订单表"，只搜 order 相关的表，不把几千张表都塞进去。

#### Provider 2: HistoryProvider — 对话历史上下文

```python
# dataworks_agent/agent/context/history_provider.py

class HistoryProvider:
    """为 LLM 提供对话历史上下文"""

    async def assemble(self, conversation_id: str, max_turns: int = 10) -> str:
        """加载最近 N 轮对话，格式化为上下文"""
        history = await self._load_history(conversation_id, max_turns)
        if not history:
            return ""

        lines = ["## 最近对话:"]
        for msg in history:
            role = "用户" if msg["role"] == "user" else "Agent"
            # 截断过长的消息
            content = msg["content"][:500]
            lines.append(f"**{role}**: {content}")
        return "\n".join(lines)
```

#### Provider 3: ProjectProvider — 项目结构上下文

```python
# dataworks_agent/agent/context/project_provider.py

class ProjectProvider:
    """为 LLM 提供项目结构上下文"""

    async def assemble(self, context: dict) -> str:
        """生成项目结构上下文"""
        lines = ["## 项目信息:"]
        lines.append(f"- 项目: {settings.dataworks_project}")
        lines.append(f"- Schema: {settings.dataworks_prod_schema}")

        # 当前会话的工作目录 (如果有的话)
        workflow_state = context.get("workflow_state", {})
        if workflow_state.get("current_step"):
            lines.append(f"- 当前进度: {workflow_state['current_step']}")

        return "\n".join(lines)
```

### 2.3 Prompt 组装器

```python
# dataworks_agent/agent/prompt_assembler.py

class PromptAssembler:
    """组装完整的 LLM prompt，包含所有上下文"""

    def __init__(self):
        self.metadata_provider = MetadataProvider()
        self.history_provider = HistoryProvider()
        self.project_provider = ProjectProvider()

    async def assemble(
        self,
        message: str,
        conversation_id: str,
        context: dict,
    ) -> list[dict]:
        """组装 messages 数组，直接传给 LLM"""

        # 1. System prompt
        system_prompt = self._build_system_prompt()

        # 2. 元数据上下文 (按需搜索)
        metadata_ctx = await self.metadata_provider.assemble(message, context)

        # 3. 对话历史
        history_ctx = await self.history_provider.assemble(conversation_id)

        # 4. 项目结构
        project_ctx = await self.project_provider.assemble(context)

        # 5. 组装完整 system message
        full_system = f"""{system_prompt}

{metadata_ctx}

{history_ctx}

{project_ctx}

## 可用工具:
{self._format_tools()}"""

        return [
            {"role": "system", "content": full_system},
            {"role": "user", "content": message},
        ]

    def _build_system_prompt(self) -> str:
        return """你是 DataWorks 智能助手，帮助用户完成数据仓库操作。

你的能力:
1. 查询表结构和元数据
2. 创建 ODS/DWD/DWS/DIM 层的表
3. 配置调度和依赖
4. 诊断任务异常
5. 分析数据血缘

你必须:
- 基于实际搜索到的表信息回答，不要编造表名
- 如果信息不足，主动向用户追问
- 关键操作（建表、删除）需要用户确认
- 返回 JSON 格式的结构化响应

响应格式:
{
  "action": "search_table | create_table | query_lineage | diagnose | clarify | ...",
  "confidence": 0.0-1.0,
  "params": {...},
  "response_text": "给用户的自然语言回复",
  "needs_clarification": false,
  "clarification_question": ""
}"""
```

### 2.4 改造后的 ChatAgent.chat()

```python
async def chat(self, message, conversation_id, ...):
    # 1. 加载上下文
    context = await self._conversation_graph.context(conversation_id)

    # 2. 组装完整 prompt (元数据 + 历史 + 项目结构)
    messages = await self._prompt_assembler.assemble(
        message, conversation_id, context
    )

    # 3. 调用 LLM (带完整上下文)
    llm_response = await self._llm.ainvoke(messages)
    parsed = self._parse_llm_response(llm_response)

    # 4. 根据 LLM 决策执行
    if parsed["needs_clarification"]:
        # LLM 判断需要追问 → 返回追问
        return ChatResponse(message=parsed["clarification_question"], ...)

    if parsed["action"] == "search_table":
        # LLM 决定先搜表 → 执行搜索 → 返回结果
        tables = await self._search_tables(parsed["params"]["keyword"])
        return ChatResponse(message=parsed["response_text"], data={"tables": tables}, ...)

    # 5. 其他动作走现有 workflow
    ...
```

## 3. 实施计划

### Phase 1: 上下文注入（核心，1.5 周）

**这是最高优先级，没有它后面都是空谈。**

1. 实现 `MetadataProvider` — 接入 `bff.search_tables()`，按关键词搜索元数据
2. 实现 `HistoryProvider` — 从 `conversation_history` 表加载最近对话
3. 实现 `ProjectProvider` — 从 `settings` 和 `ConversationGraph` 提取项目信息
4. 实现 `PromptAssembler` — 组装完整 system prompt
5. 改造 `ChatAgent.chat()` — 用 LLM + 完整上下文替代纯正则路由
6. **降级策略**：LLM 调用失败时 fallback 到现有正则路径

**验收标准**：
- 输入"查订单表"，LLM 能看到搜索到的匹配表列表
- 输入"刚才那个表加个字段"，LLM 能看到上一轮讨论的表
- LLM 返回结构化 JSON，包含 action + params + response_text

### Phase 2: Streaming 展示（1 周）

**上下文通了之后，再做 Streaming 让用户看到过程。**

1. 定义 `StreamEvent` 协议
2. `PromptAssembler.assemble()` 过程中 yield thinking/search 事件
3. 改造 `agent_sse.py` 为真流式
4. 前端 SSE 事件逐步消费 + StreamingMessage 组件

### Phase 3: 多轮对话引导（1 周）

**上下文 + Streaming 通了之后，再做追问引导。**

1. LLM 输出 `needs_clarification: true` 时，前端渲染追问卡片
2. 用户回答后，新消息带上下文合并回 LLM
3. 对话状态机：THINKING → CLARIFY → MERGING → EXECUTING → RESULT

## 4. 上下文注入的 Token 预算

LLM 上下文窗口有限，必须控制注入量：

| 上下文类型 | 预算 | 策略 |
|-----------|------|------|
| System Prompt | ~500 tokens | 固定，不可压缩 |
| 元数据 | ~1000 tokens | 按关键词搜索，最多 20 张表 |
| 对话历史 | ~800 tokens | 最近 10 轮，每轮截断 200 字 |
| 项目结构 | ~200 tokens | 精简信息 |
| 用户消息 | ~300 tokens | 原始输入 |
| **合计** | **~2800 tokens** | 剩余给 LLM 推理 |

DeepSeek-V4 上下文窗口 128K，预算绰绰有余。但要防止元数据搜索结果爆炸（比如搜"表"返回几千条），必须做 limit。

## 5. 关键场景对比

### 场景 1: "查订单表"

| | 当前 | 改造后 |
|---|---|---|
| 上下文 | raw_text only | 搜索到 3 张订单表 + 对话历史 |
| LLM 输出 | unknown, confidence=0 | action=search_table, candidates=[...] |
| 用户体验 | 卡住/空 proposal | 看到表列表，选择后查询 |

### 场景 2: "刚才那个表加个字段"

| | 当前 | 改造后 |
|---|---|---|
| 上下文 | 上轮 params（可能为空） | 上轮完整对话 + 讨论的表名 |
| LLM 输出 | unknown（正则匹配不到） | action=alter_table, table=ods_user |
| 用户体验 | 报错 | 直接执行或追问具体字段 |

### 场景 3: "帮我建个 ODS 表"

| | 当前 | 改造后 |
|---|---|---|
| 上下文 | 意图=ods_dwd_modeling，缺参数 | 意图=ods_dwd_modeling + 项目目录结构 |
| LLM 输出 | needs_clarification=true | 需要追问表名、数据源、业务域 |
| 用户体验 | 返回空 proposal | 追问 → 用户回答 → 执行 |

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 延迟 > 3s | 意图识别阶段用户等待 | 显示"思考中..."；LLM 调用加 3s 超时 |
| 元数据搜索慢 | 上下文组装耗时 | 异步预搜索；缓存热门关键词结果 |
| Token 爆炸 | 超出上下文窗口 | 严格预算控制；元数据最多 20 条 |
| LLM 输出格式错误 | 解析失败 | 重试 1 次；失败降级到正则 |
| 对话历史过长 | 上下文被稀释 | 只保留最近 10 轮；摘要旧历史 |

## 7. 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 模糊输入识别率 | ~20%（"查订单表"→unknown） | > 80% |
| 多轮对话成功率 | ~30% | > 70% |
| 首次响应时间 | 3-10s（阻塞） | < 2s（含 LLM 调用） |
| 用户追问次数 | 0（不追问） | 1-2 轮（精准追问） |

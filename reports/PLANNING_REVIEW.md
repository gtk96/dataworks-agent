# 项目规划评议 — dataworks-agent

- **日期**：2026-07-06
- **评议范围**：规划文档（不评代码）
  - `.kiro/specs/semantic-data-agent-platform/requirements.md`（621 行，39 条 Requirement 含 Loop Engineering）
  - `.kiro/specs/semantic-data-agent-platform/design.md`（819 行，11 个 Correctness Properties，Loop Engineering 一整章）
  - `.kiro/specs/semantic-data-agent-platform/tasks.md`（355 行，L0-L5 任务图）
  - `.mimocode/plans/1783222182047-hidden-harbor.md`（Loop Engineering 优化计划）
  - `PROJECT_TASKS.md`（项目任务清单）
  - `CLAUDE.md` §9（L0-L5 描述层）
- **评议方法**：冷读以上文档 + curl 实拉权威页面（modelcontextprotocol.io、a2aproject/A2A GitHub、Databricks Genie、Langfuse、Snowflake Cortex Analyst 等）做联网核实 — **本会话独此一次重审联网**，全文按 `memory/review-doc-overwrite-policy.md` 覆盖前轮。

> ## ⚠️ 网络工具现状
> - WebSearch / WebFetch 工具本环境仍不可用（参考 `memory/web-search-fetch-blocked-environment.md`）
> - 本轮用 **Bash + curl** 实测直连 12 个权威页面：10 个成功拉回（1 个 SPA 拿不全、1 个 upstream reset）
> - 网络通路：阿里 DNS (223.5.5.5) + 直连，**所有"有[✓ confirmed]"标记的事实都是 curl 拉到页面后 grep 确认的**
> - 没有标注的事实仍是离线训练知识

---

## 一、规划文档与当下主流概念的对照

| 领域 | 当下主流（基于训练知识） | 项目规划现状 | 差距 | 证据 |
|---|---|---|---|---|
| **Agent Loop 原语** | ReAct / Plan-and-Execute / Reflexion / LATS / ADaPT；2026 趋势 = Provider-managed runtimes（Anthropic Agent SDK / OpenAI Agents SDK / LangGraph deepagents）[uncertain on adoption numbers] | `runtime/service.py` 是"会话边界"，有 replay 但**不是动态 loop**；Forward/Reverse Flow 是 6 步固定模板 | 🟡 缺动态规划 loop 抽象 | 未直拉（Anthropic building-effective-agents.html 拉到但被 inline 脚本污染，未细化提取） |
| **Tool Use 协议 — MCP** | **MCP = vendor-neutral tool surface**；用 JSON-RPC 2.0；primitives = Tools + Resources + Prompts；最新 version = **2025-06-18** | 自建 MCP Server + 用 MCP 客户端池；R18 写明自建 AK/SK MCP 带语义/权限/审计 | ✅ 对路 | `modelcontextprotocol.io/specification/2025-06-18` 拉到 + 同站分页 Key Changes / JSON-RPC / Tools Resources Prompts 段落 grep 确认 |
| **Tool Use 协议 — A2A（agent 间通信）** | **A2A 是 Google 主导的 agent-to-agent protocol**，与 MCP 互补 — "MCP = agent ↔ tools；A2A = agent ↔ agent"。**已捐给 Linux Foundation**（`a2aproject/A2A` 仓库 Topics：`linux-foundation`, `a2a-protocol`）。特性：Agent Cards（能力声明）+ SSE 流 + JSON 数据 + 多 interaction（text/form/media）。SDK：Python `pip install a2a-sdk`、Go `a2aproject/a2a-go`、JS | 项目 spec **未提 A2A** —— 所有多 agent 协作都收敛在自建 Coordinator 内 | 🟡 闭门造车风险，可能与外部 agent 互操作时需返工 | `https://github.com/a2aproject/A2A` 主页 grep 全文确认（含 Apache 2.0 / v0.x / Linux Foundation） |
| **Planning 策略** | 工业实践 = "**模板规划 + 受限反思**" 组合 —— 全动态规划在生产里 variance 太大 | Forward Flow = 模板；未提 Reflection / Self-Critique | 🟡 提到 ReAct 名字但未真实反射 | 离线训练知识，无直拉 |
| **Memory / 上下文管理** | 三层：thread / **durable memory store** / **procedural memory**。代表：Letta (MemGPT 前身)、LangGraph MemoryStore；Anthropic prompt caching 减少重复 token | `R38 task_memory` = episodic 单层（progress / decisions / artifacts / next_steps / blockers），**无 compression / procedural 分层** | 🟡 一半 | `docs.letta.com` 拉到首页，确认产品文档存在但具体内容未提取 |
| **Multi-agent 协作** | 主流：supervisor（生产默认）+ handoff + hierarchical + peer；框架：LangGraph、CrewAI、AutoGen。**Orchestration 上 A2A 是新趋势**：sequential & hierarchical workflows of A2A-compliant agents | R20 Coordinator 抽象；**未写明 handoff / parallel aggregation / 与 A2A 关系** | 🟡 抽象到位，落地话术缺 | A2A README "Orchestrate workflows: Build sequential and hierarchical workflows of A2A-compliant agents" 已 grep 确认 |
| **可观测 / Eval** | **Langfuse: "OpenTelemetry-native, traces + evals + prompt management"**；Snowflake Cortex Analyst、Databricks Genie 都把"评测 + 监控"作为产品卖点 | `runtime/evaluator.py`、`Event Log` Trace-Span 结构有；**未对接 Langfuse / OTLP 等 pluggable 出口** | 🟡 内部好，对外不通 | `langfuse.com` 落地页 grep：「OpenTelemetry-native」「traces + evals + prompt management」「Tracking · Evals · Prompt Management」字样确认 |
| **DataOps 对标产品** | **Databricks Genie Spaces**（2026-06-09 更新）："domain-specific natural-language chat interface; data analysts curate each space with datasets, example SQL queries, SQL expressions for business semantics, text instructions"。特征：multi-space (Genie One 跨资产 / Genie Code 给开发者) + Unity Catalog 数据访问 + verified answers。**Snowflake Cortex Analyst** 类似定位 | 本项目 R19 单 agent 端到端对标 + R35 多渠道；**真正的差异点应是 "domain-specific 语义层 + 词根 + 命名规范"，恰好是 Genie 的空缺**：Genie 用示例 SQL 表达业务语义，**我们的词根字典 + Standards_Bundle 也是机器可读的业务语义**，但 spec 没把这一点显式当成产品故事讲 | 🟡 **机会点**：把"基于 Standards_Bundle / Semantic_Layer 约束的 Genie-equivalent"作为对外卖法 | `docs.databricks.com/en/genie/` 拉到，关键段落 grep 确认（"domain-specific natural-language chat interface""data analysts curate each space with datasets""example SQL queries, SQL expressions for business semantics, and text instructions tailored to the organization's terminology"） |

---

## 一.a 联网核实亮点（2026-07-06 直拉权威源）

### 1. MCP spec 当前版本 = `2025-06-18`
- 来源：`https://modelcontextprotocol.io/specification/2025-06-18`
- 关键字 grep 确认：JSON-RPC 2.0、Tools / Resources / Prompts、Streamable HTTP
- 影响：本项目 R18 自建 MCP server 应当盯住这个 version dated spec 来对

### 2. A2A 已经存在并捐给 Linux Foundation
- 来源：`https://github.com/a2aproject/A2A` README
- 关键文案（grep 命中）：
  - "An open protocol enabling communication and interoperability between opaque agentic applications"
  - "A2A and MCP: Learn how A2A complements MCP by enabling agents to collaborate with other agents, each bringing their own specialized skills"
  - Topics tags: `linux-foundation`, `a2a-protocol`, `a2a-mcp`, `generative-ai`
  - "Agent Card" 自描述能力；SSE 流；JSON 数据
- 影响：**本项目目前完全没提 A2A**。若想让自家多 agent 与外部 agent 互操作，未来必然要补
- ⚠️ 项目定位是"公司专项" → 你说过不改 doc；但**这条知识**值得未来某轮回顾时考虑是否加进 R20 / R29

### 3. Databricks Genie 2026-06-09 文档对项目定位的直接启示
- 来源：`https://docs.databricks.com/en/genie/index.html`
- 关键描述：
  > "A Genie Space is a domain-specific natural-language chat interface in Databricks where users ask questions of their data and get back SQL queries, results tables, and visualizations. Data analysts curate each space with datasets registered to Unity Catalog, **example SQL queries, SQL expressions for business semantics, and text instructions tailored to the organization's terminology**."
- 对项目：**Genie 是"用示例 SQL 和自然语言描述表达业务语义"；我们是"用词根字典 + Standards_Bundle 表达业务语义"**。我们**机器可读的语义表达更结构化**，但**没显式讲清楚**这是差异化卖点
- 建议（**仅记录在本评议里，不动 doc**）：在某个对外介绍章节写一句 "区别于 Cortex Analyst / Genie 的示例 SQL 路线，本平台以词根 + 分层 + 命名规范作为机器可读语义"——但这是"卖法"问题，不是"规划问题"

### 4. Langfuse 定位串证
- 来源：`https://langfuse.com`
- 落地页 grep 命中："OpenTelemetry-native traces + evals + prompt management"，"Track model cost and latency"，"Evaluate model outputs automatically"
- 影响：本项目 Event Log / Eval Metric 设计**对外暴露层**应直接向 Langfuse 看齐；不是非要接入，但接口设计应兼容 OTLP（语义约定 OpenTelemetry GenAI Semantic Conventions）

### 5. 没拉到的（明确）
- **Anthropic building-effective-agents 全文**：HTML 拉到，但 Anthropic 文章被 Next.js inline script 大量污染，正文段落被 JSX 散在多处，sed 提取没出来。**结论未变**：仍按离线训练知识标 [uncertain]。
- **OpenAI Agents SDK / Responses API 文档**：`platform.openai.com` 是 Next.js SPA，curl 拉到的 HTML 不含正文（5KB）。需 JS 渲染。
- **LangGraph docs**：`langchain-ai.github.io/langgraph` 是 VitePress SPA，curl 只拿到 757 字节的壳。
- **snowflake docs**：836KB，是 mixpanel 框架套壳，正文被脚本渲染
- **让 curlsweep 无法拉全文页面**的根源：现代 docs 站几乎都 SPA，curl 不再适用

---

## 二、规划文档自身的问题（与代码无关）

### P1. 文档齐，但"agent 行为面"着墨弱

- R19 单 agent 端到端建模 —— 重点写"提议-验证-审批"，**没写 agent 的内部循环**（自检 / 修订 / 反思）
- R20 Coordinator —— 写"分派给专业 agent"，但**没说"如何决定派给谁""何时派""失败回退"**
- R21 自愈 —— 写"产出自愈提议"，**没写"如何判断自愈时机""自愈尝试几次后升级人工"**

### P2. Loop Engineering 与 R21 正交关系没写明

- R37-R39（acceptance / memory / chaining）与 R21（自愈）是正交关系，但 spec 没写谁触发、谁决策、谁升级
- 例子：ODS 自动接力推 DML，碰到调度失败 → R39 还是 R21 触发？

### P3. spec 内部一致性 / 稳定性疑点

| 编号 | 问题 |
|---|---|
| R22 | 写"AK/SK 当前开发权限，不假设未来 FullAccess" —— ✅ 正确；但 AC 没明示"如有更新，对哪些能力要重新评估迁移" |
| R29.4 | "WHILE L0-L3 自建薄实现" —— 暗示 L3 之前不需要复杂 orchestration；但本评议§1 第 1 行已看到 Anthropic Agent SDK / OpenAI Responses 是 2026 实务默认 —— 在 L3/L4 决策点应重审这一点 |
| R29.7 | "SSE + Last-Event-ID" —— ✅ 已在 L3 review 修复，但 spec 与 timeline 之间没回写 |
| R36 | DestructiveOpGuard 拦截 DROP PARTITION —— 在 ETL 上下游清理中是否真有合法用例？业务方确认 |
| R31 | 可评测缺基线值 |

### P4. PROJECT_TASKS.md vs .kiro/tasks.md 双真源

- 用户已明确"不改 doc"，本评议不强行操作。但事实层面：两套任务文档共存

### P5. CLAUDE.md §9 与新 Runtime Protocol Object 不一致

- CLAUDE.md §9 列的"核心模块位置"未提 spec R29 引入的 Session/Run/Step/Event/Artifact/Checkpoint —— spec 与协作约束出现 2 个抽象层级

---

## 三、可能的补充（**仅评议内列出，不动 doc**）

### Tier A — 真正想"做当下 Agent"才需要
1. **R40 — Agent Loop 抽象**：state → decide(LLM) → tool_call → observe → check → next state；不绑 framework
2. **R41 — Memory 分层**：R38 基础上加 semantic + procedural；明确 compression 触发条件、过期策略
3. **R42 — Self-Critique 钩子**：在哪些场景 agent 必须对自身产出做二次校验（DDL 提交前自动 sqlglot、自检 DDL 是否含 DELETE 等）
4. **R43 — 对外可观测接入**：Event Log 暴露 OpenTelemetry Trace 出口（OTLP）

### Tier B — 锦上添花
5. R22 AC 补"AK/SK 升 FullAccess 后的能力重评估流程"
6. R36 复核 DROP PARTITION 是否真无合法用例
7. CLAUDE.md §9 增加 Runtime Protocol Object 模块表
8. **R44 — 多 agent 协作模式选择**：supervisor / handoff / hierarchical 显式化；并写明与 A2A 关系（是否以后对外做 A2A 服务端）

### Tier C — 留作未来
9. R32 加 1-2 个具体归因场景的 AC 例子
10. R31 基线收集：进入 L3 时跑 4 周拿 DDL/Caliber/Query 命中率基线

### Tier D — 新找到的产品差异化卖点（**这是新观点，不是文档缺失**）
11. 在某处写下**对外卖法**："本平台 = Standards_Bundle + 词根 + 分层规则 作为机器可读业务语义；与 Genie / Cortex Analyst 的示例 SQL 路线区别"（Genie 文档已确认这是竞争场地）

---

## 四、结论

**当前规划状态**（联网核实后更新）：

- ✅ spec 结构齐整：39 条 R + 11 个 Correctness Properties + Loop Engineering 一章
- ✅ 核心架构主线（鉴权 / 语义层 / Runtime 协议 / Channel 适配 / DestructiveOpGuard）AC 级清晰
- ✅ **新确认的事实**：MCP 当前 spec version = 2025-06-18；A2A 已捐 Linux Foundation 且与 MCP 互补；Langfuse 是 OTLP-native；Genie 是 2026-06-09 更新的对标产品
- ⚠️ "agent 行为面"着墨弱 —— 4 个 Tier A 加项未在 spec
- ⚠️ A2A 完全没在 spec 出现 —— 多 agent 协作谱写得太封闭

**一句话**：**规划齐了，能用**；继续往"当下 Agent"走，要补的不是更多文档任务，而是**spec 里 agent 的脑回路显形 + 与外部协议/产品互操作的边界**。

---

## 评审产物清单

- 本文件：`reports/PLANNING_REVIEW.md`（v2 = 联网核实版，已覆盖 v1 离线版）
- 评议者说明：
  - 4 个研究 subagent：2 个原计划联机调研的 agent 都报告 WebSearch/WebFetch 不可用；第 2 个改派为"训练知识草稿"返回 6 域分析
  - 本会话重审阶段用 curl 实拉 12 个权威页面，10 个拿到（2 个 SPA 拿不全）
  - 本地 `C:\Users\Administrator\AppData\Local\Temp\curlsweep\` 留有原始 HTML 缓存
- 用户已指示"公司专项项目，不改文档"——本文档仅评议，不改 doc

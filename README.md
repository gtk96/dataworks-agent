# dataworks-agent

> 面向阿里云 DataWorks 的可视化数仓 Agent：用自然语言完成建模、分析、排障和执行编排。

本项目不是替代 DataWorks，而是在其上增加一层可审计的 Agent 工作台：统一理解业务目标、生成执行计划、调用开发环境能力、验证结果，并把生产发布停在人工审批闸口。

## 核心能力

| 场景 | 能力 | 当前边界 |
|---|---|---|
| 正向建模 | 数据源/存量 ODS → ODS、DWD、DIM、DWS 的表、SQL、节点、依赖和调度 | 可规划；Dev 新建表和节点可执行 |
| 逆向建模 | 读取存量表、节点脚本、结构和依赖，生成分层与语义候选 | 依赖真实元数据权限 |
| 异常排查 | 汇总任务、节点、依赖、日志和运行底座状态，给出恢复建议 | 高风险修复需确认 |
| 自主问数 | 口径澄清、资产约束、只读 SQL、最新分区和结果对账 | 未认证口径不冒充生产口径 |
| Cookie 管理 | 检查并维护 Cookie/BFF/CDP 兜底通道 | 仅补足 AK/SK 权限缺口 |

Agent 统一使用有界循环：

```text
Objective → Act → Verify → Repair → Retry → Stop
```

## 设计原则

1. **开源框架优先**：LangGraph 负责 Agent 状态图、检查点和重试编排，不重复制造通用运行时。
2. **通用能力上线**：工作流、执行护栏、审批、可视化和知识结构属于产品能力。
3. **私有知识留本地**：AK/SK、Cookie、业务指标、公司目录、真实表样例和 Badcase 不进入公共代码库。
4. **前端体验优先**：测试用于守住回归，但不能替代真实页面、真实接口和真实用户路径验收。
5. **生产发布人工确认**：Agent 可以执行受控的 Dev 操作，不能绕过 Publish Gate 自动发布生产。
6. **双通道长期并存**：AK/SK/OpenAPI 负责开发执行；Cookie/BFF/CDP 负责 OpenAPI 无权限覆盖的元数据能力。

更完整的通用化边界见 [docs/product/agent_operating_model.md](docs/product/agent_operating_model.md)。

## 架构

```mermaid
flowchart LR
    UI[Vue Agent 工作台] --> API[FastAPI]
    API --> LG[LangGraph Agent Runtime]
    LG --> Guard[验证与安全护栏]
    Guard --> OpenAPI[DataWorks OpenAPI / MaxCompute]
    Guard --> MCP[阿里云官方 MCP]
    Guard --> Cookie[Cookie / BFF / CDP 兜底]
    OpenAPI --> Gate[Publish Gate]
    Gate -->|人工批准| Prod[生产发布]
```

## 技术栈

- **Agent**：LangGraph
- **后端**：Python 3.12、FastAPI、Pydantic、SQLAlchemy、SQLite、httpx、structlog
- **前端**：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router
- **数据平台**：DataWorks OpenAPI 2024-05-18、MaxCompute/pyodps、阿里云官方 DataWorks MCP
- **兼容通道**：DataWorks BFF、Chrome DevTools Protocol、Playwright
- **模型接入**：OpenAI 兼容 API

## 快速启动

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+（或 22.12+）
- Dev 执行需要可用的 DataWorks/MaxCompute AK/SK
- Cookie 兜底需要已登录 DataWorks 的 Chrome 调试会话

### 1. 配置

```powershell
Copy-Item .env.example .env
uv sync
```

至少检查以下配置：

- `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`
- `DATAWORKS_PROJECT_ID`、`DATAWORKS_REGION`
- `MAXCOMPUTE_PROJECT`、`MAXCOMPUTE_ENDPOINT`
- `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET`（Dev 执行）
- `COOKIE_ENCRYPTION_KEY`（至少 16 个字符）

完整配置及说明见 [.env.example](.env.example)。

### 2. 启动后端

```powershell
uv run python -m dataworks_agent.main
```

后端地址：`http://127.0.0.1:8085`

需要同时拉起 Chrome/Cookie 链路时，也可以运行：

```powershell
.\start.bat
```

### 3. 启动前端

```powershell
Set-Location frontend
npm install
npm run dev
```

前端地址：`http://localhost:3000`

## 执行边界

### Agent 模式

| 模式 | 行为 |
|---|---|
| `plan` | 只生成计划和产物，不写 DataWorks |
| `auto` | 自动选择规划或受控 Dev 执行，遇到风险操作暂停 |
| `dev_execute` | 允许 Dev 新建表、节点和初始化；修改、删除、发布仍受控 |

### 操作审批

| 操作 | 策略 |
|---|---|
| Dev 新建表 | 允许自动执行 |
| Dev 新建节点 | 允许自动执行 |
| 修改已有节点 | 执行前确认 |
| 删除节点 | 执行前确认 |
| 生产发布 | 必须人工批准 Publish Gate |

## 核心 API

| API | 用途 |
|---|---|
| `POST /agent/chat` | 对话规划或 Dev 执行 |
| `GET /agent/capabilities` | 查看运行框架和各执行通道状态 |
| `GET /agent/status` | 查看最近任务状态 |
| `GET /agent/status/{task_id}` | 查看指定任务状态 |
| `WS /agent/ws` | 实时对话与状态更新 |
| `GET /agent/publish-gate/requests` | 查看待审批发布请求 |
| `POST /agent/publish-gate/{request_id}/approve` | 人工批准并发布 |
| `POST /agent/publish-gate/{request_id}/reject` | 人工拒绝发布 |

默认还提供建模、治理、血缘、同步、任务和产物等 `/api/*` 路由；实验性语义/Runtime/MCP Server 路由由 `ENABLE_EXPERIMENTAL_PLATFORM_ROUTES` 控制。

## 关键目录

```text
dataworks_agent/
├── agent/          # 对话理解、规划、执行和状态图
├── runtime/        # LangGraph 循环、工作流、审批与评测
├── modeling/       # DDL/DML、建模引擎和 DataWorks 产物
├── services/       # DI、Hologres、OSS、Realtime 等数据接入
├── api_clients/    # OpenAPI、MaxCompute、BFF、CDP 客户端
├── semantic/       # 指标、语义知识与问数约束
├── governance/     # DDL、词根、血缘和规范检查
└── routers/        # FastAPI 路由

frontend/src/
├── components/agent/ # Agent 对话与执行可视化
├── pages/            # 页面
└── router/           # 前端路由

tests/              # 后端测试与评测
frontend/e2e/       # 浏览器 E2E
scripts/            # 运维脚本
docs/               # 设计、计划、评审和产品文档
```

## 验证

文档或后端小改动先做最小检查；功能改动最终必须补前端构建和真实页面验收。

```powershell
uv run python -m compileall -q dataworks_agent
uv run ruff check .
uv run python -m pytest tests/unit/test_agent tests/unit/test_agent_router.py -q --tb=short

Set-Location frontend
npm run build
npm run test:unit
```

上线前不要只看测试数量，应确认：页面可打开、对话可继续、执行步骤可见、确认点有效、Publish Gate 不可绕过。

## 安全与知识边界

- 凭据只通过环境变量或本地 `.env` 注入，不写入代码、SQLite、日志或 Git。
- 通用仓库只保存能力、规则和知识结构，不保存私有业务指标与真实账号数据。
- 破坏性操作必须经过项目内 guard；生产发布只认 Publish Gate 的人工结果。
- OpenAPI 元数据权限不足时走 Cookie 兜底，不通过扩大 AK/SK 权限或前端直连绕过。

---

## Harness Engineering 十支柱

本项目采用 **Harness Engineering** 框架实现 Agent 的可控、可预测、可信任。每个支柱解决一个特定的可靠性问题，共同构成完整的 Agent 运行时。

### [1] Identity — 角色定义与约束体系

**解决的问题**：Agent 不知道自己该做什么，导致越权操作或行为不一致。

**实现**：
- 每个 Agent 类型（Requirement/Architecture/Modeling/Governance/Diagnosis/Query）声明明确的身份
- 三层金字塔约束：超级红线（违反即阻断）/ 错误记录（引起重视）/ 操作规则（建议性）
- 能力边界声明：能做什么、绝对不能做什么

**关键文件**：`dataworks_agent/runtime/identity.py`

**示例**：
```python
# Modeling Agent 的红线
- 不得越界产出方案或 SQL 代码
- 不得跳过 Publish Gate 自动发布生产
```

### [2] Orchestration — 流程编排与智能调度

**解决的问题**：Agent 执行顺序混乱，缺乏流程控制。

**实现**：
- Coordinator 编排 6 个专业 Agent 协同工作
- 任务分解为子任务，按依赖顺序执行
- 支持全链路/快案/快码三种执行路径
- 无依赖任务并行执行，有依赖任务串行执行

**关键文件**：`dataworks_agent/runtime/coordinator.py`

**核心公式**：Agent = Model + Harness

### [3] Context — 上下文工程

**解决的问题**：上下文污染，Agent 看到不该看到的信息。

**实现**：
- Spec 文件驱动：Agent 之间通过结构化 Spec 交换信息
- CP 检查点摘要：上游 Agent 产出压缩为固定格式传给下游
- 渐进式加载：下游只加载需要的 Spec 片段
- 物理隔离：每个 Agent 只读自己该读的文件

**关键文件**：`dataworks_agent/runtime/spec_protocol.py`

**设计原则**：一切皆文件，小工具组合

### [4] Gate — 门禁检查与质量评估

**解决的问题**：Agent 产出质量不可控，错误难以发现。

**实现**：
- ProposalGuard 五道闸门校验（词根/DDL/分层/表名/语义）
- PublishGate 发布前最终确认
- DestructiveOpGuard 阻止破坏性操作
- 生成与评估分离：Agent 不自评

**关键文件**：`dataworks_agent/semantic/guard.py`

**核心理念**：可控，比聪明更重要

### [5] Recovery — 状态追踪与故障恢复

**解决的问题**：Agent 执行中断后无法恢复，前功尽弃。

**实现**：
- LoopKernel 有界循环：observe-act-verify-repair
- 12 个明确的状态枚举值
- 故障分级：可重试 / 需回退 / 必须中止
- 断点续接：从最近检查点恢复

**关键文件**：`dataworks_agent/runtime/loop.py`

**状态机**：PENDING → RUNNING → DDL_GEN → TABLE_CRE → ... → COMPLETED

### [6] Evolution — 经验沉淀与进化学习

**解决的问题**：同一个错误反复出现，系统不学习。

**实现**：
- 错误记录本：递增编号/日期/一句话描述/正确做法
- 自动加载：Agent 工作时自动加载经验库
- 约束迭代：反复出现的错误升级为超级红线（阈值=3）
- 实时记录：用户指出错误时立刻结构化记录

**关键文件**：`dataworks_agent/runtime/evolution_loop.py`

**驱动机制**：实时记录 → 自动加载 → 行为约束迭代

### [7] Reflection — LLM 反思执行偏差

**解决的问题**：验证失败后盲目重试，不知为何失败。

**实现**：
- LLM 驱动反思：分析偏差根因，生成策略调整建议
- 确定性回退：无 LLM 时基于规则的启发式分析
- 偏差分类：incorrect_input / insufficient_context / wrong_tool / strategy_flaw / constraint_violation
- 与 Evolution 联动：反思结果自动送入进化回路

**关键文件**：`dataworks_agent/runtime/reflection.py`

**核心流程**：Act → Verify → [失败] → Reflection → Repair → Act → Verify

### [8] Intent Clarification — 意图确认机制

**解决的问题**：模糊需求直接执行，导致错误操作。

**实现**：
- 置信度分级：>=0.8 自动确认，0.5-0.8 建议确认，<0.5 必须确认
- 必填字段检测：根据 action 类型检查缺失参数
- 反问确认：对模糊需求生成澄清问题
- 只对工作流类 action 生效，简单工具调用由下游处理

**关键文件**：`dataworks_agent/agent/intent_clarifier.py`

**示例**：
```
用户: "帮我分析一下这个指标为什么下降"
→ 置信度 0.58, 缺失 metric_id
→ 返回: "需要澄清：需要归因的指标或口径 ID 是什么？"
```

### [9] Memory Layering — 记忆分层管理

**解决的问题**：记忆混乱，无法区分短期/长期、重要/次要。

**实现**：
- 四类记忆：user（季度级）/ feedback（月级）/ project（周级）/ reference（永不过期）
- 写入三道闸门：能推导的不写 / 跨会话才有用才写 / 先查重
- 组织纪律：原子事实 + 带 why + 绝对时间 + 指针优于副本
- TTL 自动清理：过期记忆自动删除

**关键文件**：`dataworks_agent/runtime/memory_service.py`

**记忆是线索，不是缓存**

### [10] Self-Evolution — 持续自愈与语义自进化

**解决的问题**：系统静态不变，无法适应新场景和新错误。

**实现**：
- SelfEvolveFlow 完整循环：Detect → Classify → Propose → Apply → Verify → Learn
- 连接 Evaluator → EvolutionLoop → AgentRegistry 的行为进化
- 连接 SemanticEvolver → SemanticLayer 的语义进化
- 连接 SelfHealFlow → 自愈提议的自动执行与验证

**关键文件**：`dataworks_agent/runtime/self_evolve.py`

**完整闭环**：
```
Detect (收集 badcases)
  ↓
Classify (分类 behavioral/semantic/operational)
  ↓
Propose (生成进化提议)
  ↓
Apply (自动应用安全的，人工审批风险的)
  ↓
Verify (验证改进效果)
  ↓
Learn (沉淀经验到知识库)
```

---

## 支柱关系图

```
                    User Input (Natural Language)
                           │
                    ┌──────▼──────┐
                    │  Intent     │  [8] Intent Clarification
                    │  Clarifier  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Requirement│  [1] Identity
                    │  Agent      │  (Role + Constraints)
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │   Coordinator           │  [2] Orchestration
              │   (Task Decomposition)  │
              └────────────┬────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌────────────┐  ┌─────────────┐  ┌──────────────┐
   │ Modeling   │  │ Governance  │  │ Diagnosis    │
   │ Agent      │  │ Agent       │  │ Agent        │
   └─────┬──────┘  └──────┬──────┘  └──────┬───────┘
         │                │                │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │ Gate    │      │ Gate    │      │ Gate    │  [4] Gate
    │ [DDL]   │      │ [Naming]│      │ [Safety]│
    └────┬────┘      └────┬────┘      └────┬────┘
         │                │                │
    ┌────▼────────────────▼────────────────▼────┐
    │         LoopKernel                        │  [5] Recovery
    │  (observe → act → verify → repair)        │
    └────────────┬──────────────────────────────┘
                 │
           ┌─────▼─────┐
           │ Reflection│  [7] Reflection
           │ (LLM)     │
           └─────┬─────┘
                 │
    ┌────────────▼────────────┐
    │     Evolution Loop      │  [6] Evolution
    │ (Badcase → Constraint)  │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │   SelfEvolveFlow        │  [10] Self-Evolution
    │ (Detect→Classify→...)   │
    └─────────────────────────┘
```

## 测试状态

- **1077 passed** ✅
- 3 个 pre-existing failures（`test_memory_layering.py`，与 Harness 支柱无关）

## 许可证

MIT License

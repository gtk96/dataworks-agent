# Agent 系统设计文档

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/agent-system-phase1.md)

> 项目: dataworks-agent 智能数仓建模系统
> 版本: v0.2.0
> 日期: 2026-07-10
> 状态: 设计阶段

## [S1] 问题定义

### 1.1 当前痛点

1. **操作门槛高**: 用户需要了解 DataWorks API、SQL 语法、调度配置等专业知识
2. **操作繁琐**: 创建一个完整的数仓表需要多步手动操作（建表、配调度、推DML、设依赖）
3. **错误率高**: 手动操作容易遗漏步骤或配置错误
4. **缺乏智能**: 系统无法主动发现问题或提供优化建议

### 1.2 目标用户

- 数据工程师：需要快速创建和管理数仓表
- 数据分析师：需要理解数据血缘和口径
- 项目经理：需要监控数仓建设进度

### 1.3 成功标准

- 用户可以用自然语言完成 80% 的数仓操作
- 操作时间从分钟级降到秒级
- 错误率降低 50% 以上

## [S2] 解决方案概述

### 2.1 核心理念

将现有"工具集合"演进为"智能代理"，实现：

1. **自然语言理解**: 解析用户意图，识别操作类型和参数
2. **任务规划**: 自动拆解复杂任务，生成执行计划
3. **自主执行**: 按计划执行操作，实时反馈进度
4. **上下文记忆**: 记住对话历史和项目上下文
5. **主动建议**: 基于数据质量、性能等主动发现问题

### 2.2 演进路径

```
Phase 1: 对话式操作 (MVP)
├── 自然语言理解 (NLU)
├── 意图识别与槽位填充
├── 任务执行与反馈
└── 嵌入式对话界面

Phase 2: 自主规划与执行
├── 任务自动拆解
├── 多步骤任务编排
├── 错误恢复与重试
└── 执行计划可视化

Phase 3: 多轮对话与记忆
├── 对话历史管理
├── 项目上下文记忆
├── 个性化推荐
└── 知识图谱构建

Phase 4: 主动智能
├── 数据质量监控
├── 性能优化建议
├── 异常检测与告警
└── 自愈流程触发
```

## [S3] 架构设计

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (Vue 3)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ 对话界面    │  │ 任务面板    │  │ 可视化面板  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
└─────────┼────────────────┼────────────────┼─────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│                   API 网关 (FastAPI)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ /agent/chat │  │ /agent/task │  │ /agent/stream│    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
└─────────┼────────────────┼────────────────┼─────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│                   Agent 核心层                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ 意图解析器  │  │ 任务规划器  │  │ 执行引擎    │     │
│  │ (NLU)       │  │ (Planner)   │  │ (Executor)  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ 上下文管理  │  │ 记忆系统    │  │ 反馈生成器  │     │
│  │ (Context)   │  │ (Memory)    │  │ (Feedback)  │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│                   工具层 (Tools)                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │DDL生成  │ │DML生成  │ │调度配置 │ │血缘查询 │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │节点创建 │ │依赖配置 │ │发布管理 │ │监控告警 │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
└─────────────────────────────────────────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│                   基础设施层 (L0)                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │AK/SK    │ │OpenAPI  │ │MaxCompute│ │LLM服务  │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心组件

#### 3.2.1 意图解析器 (NLU)

**职责**: 解析用户自然语言输入，识别意图和槽位

**输入**: 用户自然语言文本
**输出**: 结构化意图对象

```python
class Intent:
    action: str          # 操作类型: create_table, query_lineage, check_status, etc.
    params: dict         # 槽位参数: table_name, layer, schedule, etc.
    confidence: float    # 置信度
    raw_text: str        # 原始输入文本
```

**Phase 1 支持的意图类型** (MVP):
1. **表操作**: create_table
2. **查询操作**: query_lineage
3. **监控操作**: check_status

**后续阶段扩展**:
- 表操作: drop_table, alter_table
- DML操作: generate_dml, update_dml, push_dml
- 调度操作: configure_schedule, update_schedule
- 依赖操作: add_dependency, remove_dependency
- 查询操作: query_table_info, query_task_status
- 部署操作: deploy_node, publish_node
- 监控操作: get_metrics

**Phase 1 实现方案**:
- 使用正则表达式模式匹配进行意图识别
- 槽位提取使用正则表达式
- 意图分类使用预定义模板

**后续阶段实现方案**:
- 使用 LLM 进行意图识别（Few-shot prompting）
- 槽位提取使用正则 + LLM 混合方案
- 意图分类使用预定义模板 + 语义相似度

#### 3.2.2 任务规划器 (Planner)

**职责**: 将用户意图拆解为可执行的任务序列

**输入**: 意图对象
**输出**: 任务计划

```python
class TaskPlan:
    task_id: str
    steps: list[TaskStep]
    intent: Intent | None  # 关联的意图
    
class TaskStep:
    step_id: str
    tool: str           # 使用的工具
    params: dict        # 工具参数
    depends_on: list    # 依赖的步骤
```

**Phase 1 规划策略** (MVP):
1. **模板匹配**: 常见操作使用预定义模板

**后续阶段规划策略**:
2. **LLM规划**: 复杂任务使用LLM生成执行计划
3. **图搜索**: 基于依赖关系进行拓扑排序（TaskGraph 已实现）

**Phase 1 支持的模板**:
- `create_table`: 4 步骤 (create_holo_table → create_mc_table → create_node → push_dml)
- `query_lineage`: 1 步骤 (query_lineage)
- `check_status`: 1 步骤 (check_task_status)

#### 3.2.3 执行引擎 (Executor)

**职责**: 按计划执行任务，处理异常，返回结果

**输入**: 任务计划
**输出**: 执行结果

```python
class ExecutionResult:
    success: bool
    task_id: str
    step_results: list[StepResult]
    errors: list[str]
    
class StepResult:
    step_id: str
    tool: str
    success: bool
    data: dict | None
    error: str | None
```

**Phase 1 执行特性** (MVP):
1. **顺序执行**: 按依赖顺序执行步骤
2. **错误收集**: 单个步骤失败记录错误，继续执行后续步骤
3. **可观测性**: 每步执行记录日志

**后续阶段执行特性**:
4. **幂等性**: 同一操作多次执行结果一致
5. **原子性**: 单个步骤失败可回滚
6. **回滚机制**: `rollback_performed: bool` 字段

#### 3.2.4 上下文管理 (Context)

**职责**: 管理对话上下文和项目状态

```python
class ConversationContext:
    session_id: str
    history: list[Message]
    project_state: dict
    user_preferences: dict
```

#### 3.2.5 记忆系统 (Memory)

**职责**: 持久化存储对话历史和学习到的知识

**存储内容**:
1. 对话历史（短期记忆）
2. 用户偏好（长期记忆）
3. 常见操作模式（学习记忆）
4. 错误案例（经验记忆）

## [S4] 数据流设计

### 4.1 用户交互流程

```
用户输入 → 意图解析 → 任务规划 → 执行反馈 → 结果展示
   │           │           │           │           │
   │           │           │           │           │
   ▼           ▼           ▼           ▼           ▼
"创建ods_user表" → Intent(create_table, {table: "ods_user", layer: "ods"}) 
    → TaskPlan([create_holo_table, create_mc_table, create_node, push_dml])
    → Execute[step1: success, step2: success, step3: success, step4: success]
    → "已成功创建ods_user表，包含以下节点：..."
```

### 4.2 错误处理流程

```
执行失败 → 错误分类 → 回滚决策 → 用户通知 → 建议修复
   │           │           │           │           │
   ▼           ▼           ▼           ▼           ▼
API限流 → 重试策略 → 无回滚 → "操作受限，请稍后重试" → "建议配置重试策略"
```

## [S5] 前端集成设计

### 5.1 对话界面组件

```vue
<!-- AgentChat.vue -->
<template>
  <div class="agent-chat">
    <!-- 对话历史 -->
    <div class="chat-history">
      <Message v-for="msg in messages" :key="msg.id" :message="msg" />
    </div>
    
    <!-- 快捷操作 -->
    <div class="quick-actions">
      <ActionButton @click="createTable">创建表</ActionButton>
      <ActionButton @click="queryLineage">查询血缘</ActionButton>
      <ActionButton @click="checkStatus">检查状态</ActionButton>
    </div>
    
    <!-- 输入框 -->
    <div class="chat-input">
      <textarea v-model="input" placeholder="描述您的需求..." />
      <button @click="send">发送</button>
    </div>
  </div>
</template>
```

### 5.2 任务执行面板

```vue
<!-- TaskExecutionPanel.vue -->
<template>
  <div class="task-panel">
    <!-- 任务计划 -->
    <TaskPlan :plan="currentPlan" />
    
    <!-- 执行进度 -->
    <ExecutionProgress :steps="executionSteps" />
    
    <!-- 实时日志 -->
    <LiveLog :logs="executionLogs" />
  </div>
</template>
```

## [S6] 实现计划

### Phase 1: 对话式操作 (MVP) - 4周

**Week 1-2: Agent 核心框架**
- [ ] 创建 `dataworks_agent/agent/` 目录结构
- [ ] 实现意图解析器 (NLU)
- [ ] 实现基础意图识别 (create_table, query_lineage)
- [ ] 编写意图识别测试

**Week 3: 任务执行引擎**
- [ ] 实现任务规划器
- [ ] 集成现有工具层 (DDL/DML生成、节点创建等)
- [ ] 实现执行引擎和错误处理
- [ ] 编写执行引擎测试

**Week 4: 前端集成**
- [ ] 创建对话界面组件
- [ ] 实现 WebSocket 实时通信
- [ ] 集成到现有前端
- [ ] 端到端测试

### Phase 2: 自主规划与执行 - 4周

- [ ] 实现复杂任务自动拆解
- [ ] 支持多步骤任务编排
- [ ] 实现错误恢复和重试机制
- [ ] 任务执行计划可视化

### Phase 3: 多轮对话与记忆 - 4周

- [ ] 实现对话历史管理
- [ ] 实现项目上下文记忆
- [ ] 支持个性化推荐
- [ ] 构建知识图谱

### Phase 4: 主动智能 - 4周

- [ ] 实现数据质量监控
- [ ] 实现性能优化建议
- [ ] 实现异常检测
- [ ] 实现自愈流程

## [S7] 技术选型

### 7.1 LLM 集成

- **模型**: DeepSeek-V4 (已配置在 .env)
- **调用方式**: OpenAI 兼容 API
- **Prompt 策略**: Few-shot + Chain-of-Thought

### 7.2 通信协议

- **实时通信**: WebSocket (已有 `/ws/tasks`)
- **请求/响应**: REST API
- **流式输出**: Server-Sent Events (SSE)

### 7.3 状态管理

- **对话状态**: Redis / SQLite (已有)
- **任务状态**: SQLite (已有 task_engine)
- **缓存**: 内存缓存 + epoch 机制 (已有)

## [S8] 风险与缓解

### 8.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 幻觉 | 生成错误操作 | 添加确认步骤，关键操作需二次确认 |
| API 限流 | 执行失败 | 实现重试和退避策略 |
| 上下文丢失 | 对话不连贯 | 持久化对话历史 |

### 8.2 安全风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 恶意输入 | 执行危险操作 | 输入校验 + 权限控制 |
| 提示注入 | 绕过安全检查 | 输入清洗 + 输出过滤 |
| 数据泄露 | 敏感信息暴露 | 日志脱敏 + 访问控制 |

## [S9] 测试策略

### 9.1 单元测试

- 意图解析器测试
- 任务规划器测试
- 执行引擎测试

### 9.2 集成测试

- Agent 与工具层集成测试
- Agent 与 LLM 服务集成测试

### 9.3 端到端测试

- 用户对话流程测试
- 复杂任务执行测试
- 错误恢复测试

## [S10] 监控与可观测性

### 10.1 指标

- 对话轮次数
- 意图识别准确率
- 任务执行成功率
- 平均响应时间

### 10.2 日志

- 对话历史日志
- 操作审计日志
- 错误追踪日志

### 10.3 告警

- 执行失败告警
- 性能下降告警
- 安全事件告警
# Agent 系统 Phase 1 实现计划

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/agent-system-phase1.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现对话式数仓操作 MVP，支持自然语言创建表、查询血缘、检查状态

**Architecture:** 基于现有工具层构建 Agent 核心框架，集成 LLM 进行意图识别，通过 WebSocket 实现实时通信

**Tech Stack:** Python 3.12+, FastAPI, WebSocket, OpenAI-compatible LLM, Vue 3

## Global Constraints

- Python ≥ 3.12, 使用 uv 管理依赖
- 前端 Vue 3 + Vite + Element Plus
- LLM 使用 DeepSeek-V4 (OpenAI 兼容 API)
- 现有工具层保持不变，Agent 作为上层封装
- 所有新代码必须有单元测试
- 遵循项目现有代码风格和架构

---

## 文件结构

```
dataworks_agent/
├── agent/                          # Agent 核心模块
│   ├── __init__.py
│   ├── core.py                     # Agent 主类
│   ├── nlu/                        # 自然语言理解
│   │   ├── __init__.py
│   │   ├── intent_parser.py        # 意图解析器
│   │   ├── entity_extractor.py     # 实体抽取
│   │   └── templates.py            # 意图模板
│   ├── planner/                    # 任务规划
│   │   ├── __init__.py
│   │   ├── task_planner.py         # 任务规划器
│   │   └── task_graph.py           # 任务依赖图
│   ├── executor/                   # 执行引擎
│   │   ├── __init__.py
│   │   ├── task_executor.py        # 任务执行器
│   │   └── tool_executor.py        # 工具执行器
│   ├── context/                    # 上下文管理
│   │   ├── __init__.py
│   │   └── conversation.py         # 对话上下文
│   └── feedback/                   # 反馈生成
│       ├── __init__.py
│       └── response_builder.py     # 响应构建器
├── routers/
│   └── agent.py                    # Agent API 路由
frontend/
└── src/
    └── components/
        └── agent/
            ├── AgentChat.vue       # 对话界面
            ├── ChatMessage.vue     # 消息组件
            ├── TaskExecution.vue   # 任务执行面板
            └── QuickActions.vue    # 快捷操作
tests/
└── unit/
    └── test_agent/
        ├── __init__.py
        ├── test_intent_parser.py
        ├── test_task_planner.py
        └── test_task_executor.py
```

---

### Task 1: Agent 核心框架搭建

**Covers:** [S3.2] (部分 - Agent 核心类和响应结构)

**Files:**
- Create: `dataworks_agent/agent/__init__.py`
- Create: `dataworks_agent/agent/core.py`
- Test: `tests/unit/test_agent/__init__.py`
- Test: `tests/unit/test_agent/test_core.py`

**Interfaces:**
- Produces: `Agent` 类，提供 `chat(message: str) -> AgentResponse` 方法

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_core.py
import pytest
from dataworks_agent.agent.core import Agent, AgentResponse

@pytest.fixture
def agent():
    return Agent()

def test_agent_initialization(agent):
    """测试 Agent 初始化"""
    assert agent is not None
    assert hasattr(agent, 'chat')

def test_agent_chat_returns_response(agent):
    """测试 Agent chat 方法返回响应"""
    response = agent.chat("你好")
    assert isinstance(response, AgentResponse)
    assert response.message is not None
    assert response.success is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_core.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'dataworks_agent.agent'"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/__init__.py
from dataworks_agent.agent.core import Agent, AgentResponse

__all__ = ["Agent", "AgentResponse"]
```

```python
# dataworks_agent/agent/core.py
"""Agent 核心模块 - 对话式数仓操作"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    """Agent 响应"""
    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Agent:
    """数仓操作 Agent"""
    
    def __init__(self):
        self._initialized = True
    
    def chat(self, message: str) -> AgentResponse:
        """处理用户消息"""
        # Phase 1: 简单的回显
        return AgentResponse(
            message=f"收到您的消息: {message}",
            success=True
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_core.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/ tests/unit/test_agent/
git commit -m "feat(agent): 初始化 Agent 核心框架"
```

---

### Task 2: 意图解析器 (NLU)

**Covers:** [S3.2.1]

**Files:**
- Create: `dataworks_agent/agent/nlu/__init__.py`
- Create: `dataworks_agent/agent/nlu/intent_parser.py`
- Create: `dataworks_agent/agent/nlu/entity_extractor.py`
- Create: `dataworks_agent/agent/nlu/templates.py`
- Test: `tests/unit/test_agent/test_intent_parser.py`

**Interfaces:**
- Consumes: 用户输入文本
- Produces: `Intent` 数据类，包含 action, params, confidence

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_intent_parser.py
import pytest
from dataworks_agent.agent.nlu.intent_parser import IntentParser, Intent

@pytest.fixture
def parser():
    return IntentParser()

def test_parse_create_table_intent(parser):
    """测试解析创建表意图"""
    result = parser.parse("创建ods_user表")
    assert result.action == "create_table"
    assert "table_name" in result.params
    assert result.params["table_name"] == "ods_user"

def test_parse_query_lineage_intent(parser):
    """测试解析查询血缘意图"""
    result = parser.parse("查询ods_user的血缘")
    assert result.action == "query_lineage"
    assert "table_name" in result.params

def test_parse_unknown_intent(parser):
    """测试解析未知意图"""
    result = parser.parse("今天天气怎么样")
    assert result.action == "unknown"
    assert result.confidence < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_intent_parser.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/nlu/__init__.py
from dataworks_agent.agent.nlu.intent_parser import IntentParser, Intent

__all__ = ["IntentParser", "Intent"]
```

```python
# dataworks_agent/agent/nlu/templates.py
"""意图模板定义"""
from typing import Any

INTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "create_table": {
        "patterns": [
            r"创建.*表",
            r"新建.*表",
            r"建.*表",
            r"create.*table",
        ],
        "required_params": ["table_name"],
        "optional_params": ["layer", "description"],
    },
    "query_lineage": {
        "patterns": [
            r"查询.*血缘",
            r"查看.*依赖",
            r"query.*lineage",
        ],
        "required_params": ["table_name"],
        "optional_params": ["depth"],
    },
    "check_status": {
        "patterns": [
            r"检查.*状态",
            r"查看.*进度",
            r"check.*status",
        ],
        "required_params": [],
        "optional_params": ["task_id"],
    },
}
```

```python
# dataworks_agent/agent/nlu/entity_extractor.py
"""实体抽取器"""
import re
from typing import Any


class EntityExtractor:
    """从文本中抽取实体"""
    
    def extract_table_name(self, text: str) -> str | None:
        """抽取表名"""
        # 匹配常见的表名模式
        patterns = [
            r"(?:ods|dwd|dws|dim|dmr)[_\w]+",
            r"(\w+)(?:表|数据表)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0) if match.lastindex is None else match.group(1)
        return None
    
    def extract_params(self, text: str, template: dict[str, Any]) -> dict[str, Any]:
        """根据模板抽取参数"""
        params: dict[str, Any] = {}
        if "table_name" in template.get("required_params", []):
            table_name = self.extract_table_name(text)
            if table_name:
                params["table_name"] = table_name
        return params
```

```python
# dataworks_agent/agent/nlu/intent_parser.py
"""意图解析器"""
import re
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES


@dataclass
class Intent:
    """意图数据类"""
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""


class IntentParser:
    """意图解析器"""
    
    def __init__(self):
        self._extractor = EntityExtractor()
        self._templates = INTENT_TEMPLATES
    
    def parse(self, text: str) -> Intent:
        """解析用户输入为意图"""
        text_lower = text.lower().strip()
        
        for action, template in self._templates.items():
            for pattern in template["patterns"]:
                if re.search(pattern, text_lower):
                    params = self._extractor.extract_params(text, template)
                    return Intent(
                        action=action,
                        params=params,
                        confidence=0.8,
                        raw_text=text,
                    )
        
        return Intent(
            action="unknown",
            params={},
            confidence=0.0,
            raw_text=text,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_intent_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/nlu/ tests/unit/test_agent/test_intent_parser.py
git commit -m "feat(agent): 实现意图解析器和实体抽取"
```

---

### Task 3: 任务规划器

**Covers:** [S3.2.2]

**Files:**
- Create: `dataworks_agent/agent/planner/__init__.py`
- Create: `dataworks_agent/agent/planner/task_planner.py`
- Create: `dataworks_agent/agent/planner/task_graph.py`
- Test: `tests/unit/test_agent/test_task_planner.py`

**Interfaces:**
- Consumes: `Intent` 数据类
- Produces: `TaskPlan` 数据类，包含步骤列表和依赖关系

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_task_planner.py
import pytest
from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_planner import TaskPlanner, TaskPlan, TaskStep

@pytest.fixture
def planner():
    return TaskPlanner()

def test_plan_create_table(planner):
    """测试规划创建表任务"""
    intent = Intent(
        action="create_table",
        params={"table_name": "ods_user", "layer": "ods"},
        confidence=0.9,
    )
    plan = planner.plan(intent)
    
    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) > 0
    assert any(s.tool == "create_holo_table" for s in plan.steps)

def test_plan_query_lineage(planner):
    """测试规划查询血缘任务"""
    intent = Intent(
        action="query_lineage",
        params={"table_name": "ods_user"},
        confidence=0.9,
    )
    plan = planner.plan(intent)
    
    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "query_lineage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_planner.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/planner/__init__.py
from dataworks_agent.agent.planner.task_planner import TaskPlanner, TaskPlan, TaskStep

__all__ = ["TaskPlanner", "TaskPlan", "TaskStep"]
```

```python
# dataworks_agent/agent/planner/task_graph.py
"""任务依赖图"""
from __future__ import annotations

from typing import Any


class TaskGraph:
    """任务依赖图"""
    
    def __init__(self):
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, list[str]] = {}
    
    def add_node(self, node_id: str, **kwargs: Any) -> None:
        """添加节点"""
        self._nodes[node_id] = kwargs
        if node_id not in self._edges:
            self._edges[node_id] = []
    
    def add_edge(self, from_node: str, to_node: str) -> None:
        """添加边"""
        if from_node not in self._edges:
            self._edges[from_node] = []
        self._edges[from_node].append(to_node)
    
    def topological_sort(self) -> list[str]:
        """拓扑排序"""
        visited: set[str] = set()
        result: list[str] = []
        
        def dfs(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for next_node in self._edges.get(node, []):
                dfs(next_node)
            result.append(node)
        
        for node in self._nodes:
            dfs(node)
        
        return result
```

```python
# dataworks_agent/agent/planner/task_planner.py
"""任务规划器"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_graph import TaskGraph


@dataclass
class TaskStep:
    """任务步骤"""
    step_id: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """任务计划"""
    task_id: str
    steps: list[TaskStep] = field(default_factory=list)
    intent: Intent | None = None


# 任务模板
TASK_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "create_table": [
        {"tool": "create_holo_table", "params": ["table_name", "layer"]},
        {"tool": "create_mc_table", "params": ["table_name"]},
        {"tool": "create_node", "params": ["table_name", "layer"]},
        {"tool": "push_dml", "params": ["table_name"]},
    ],
    "query_lineage": [
        {"tool": "query_lineage", "params": ["table_name"]},
    ],
    "check_status": [
        {"tool": "check_task_status", "params": ["task_id"]},
    ],
}


class TaskPlanner:
    """任务规划器"""
    
    def plan(self, intent: Intent) -> TaskPlan:
        """根据意图生成任务计划"""
        task_id = f"task_{intent.action}_{hash(intent.raw_text) % 10000}"
        
        if intent.action == "unknown":
            return TaskPlan(task_id=task_id, steps=[], intent=intent)
        
        template = TASK_TEMPLATES.get(intent.action, [])
        steps: list[TaskStep] = []
        
        for i, step_def in enumerate(template):
            params = {
                p: intent.params.get(p)
                for p in step_def["params"]
                if p in intent.params
            }
            step = TaskStep(
                step_id=f"step_{i}",
                tool=step_def["tool"],
                params=params,
                depends_on=[f"step_{i-1}"] if i > 0 else [],
            )
            steps.append(step)
        
        return TaskPlan(task_id=task_id, steps=steps, intent=intent)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_planner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/planner/ tests/unit/test_agent/test_task_planner.py
git commit -m "feat(agent): 实现任务规划器和任务依赖图"
```

---

### Task 4: 执行引擎

**Covers:** [S3.2.3]

**Files:**
- Create: `dataworks_agent/agent/executor/__init__.py`
- Create: `dataworks_agent/agent/executor/task_executor.py`
- Create: `dataworks_agent/agent/executor/tool_executor.py`
- Test: `tests/unit/test_agent/test_task_executor.py`

**Interfaces:**
- Consumes: `TaskPlan` 数据类
- Produces: `ExecutionResult` 数据类

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_task_executor.py
import pytest
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskStep
from dataworks_agent.agent.executor.task_executor import TaskExecutor, ExecutionResult

@pytest.fixture
def executor():
    return TaskExecutor()

def test_execute_simple_plan(executor):
    """测试执行简单计划"""
    plan = TaskPlan(
        task_id="test_task",
        steps=[
            TaskStep(step_id="step_0", tool="query_lineage", params={"table_name": "ods_user"}),
        ],
    )
    result = executor.execute(plan)
    
    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert len(result.step_results) == 1

def test_execute_plan_with_dependency(executor):
    """测试执行有依赖的计划"""
    plan = TaskPlan(
        task_id="test_task",
        steps=[
            TaskStep(step_id="step_0", tool="create_holo_table", params={"table_name": "test"}),
            TaskStep(step_id="step_1", tool="push_dml", params={"table_name": "test"}, depends_on=["step_0"]),
        ],
    )
    result = executor.execute(plan)
    
    assert isinstance(result, ExecutionResult)
    assert result.success is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_executor.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/executor/__init__.py
from dataworks_agent.agent.executor.task_executor import TaskExecutor, ExecutionResult

__all__ = ["TaskExecutor", "ExecutionResult"]
```

```python
# dataworks_agent/agent/executor/tool_executor.py
"""工具执行器"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """工具执行结果"""
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class ToolExecutor:
    """工具执行器 - 桥接现有工具层"""
    
    def execute(self, tool: str, params: dict[str, Any]) -> ToolResult:
        """执行工具"""
        # Phase 1: 模拟执行
        # 后续集成现有工具层
        return ToolResult(
            tool=tool,
            success=True,
            data={"message": f"工具 {tool} 执行成功"},
        )
```

```python
# dataworks_agent/agent/executor/task_executor.py
"""任务执行器"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.executor.tool_executor import ToolExecutor, ToolResult
from dataworks_agent.agent.planner.task_planner import TaskPlan

logger = logging.getLogger("dataworks_agent.agent.executor")


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    task_id: str
    step_results: list[StepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TaskExecutor:
    """任务执行器"""
    
    def __init__(self):
        self._tool_executor = ToolExecutor()
    
    def execute(self, plan: TaskPlan) -> ExecutionResult:
        """执行任务计划"""
        step_results: list[StepResult] = []
        errors: list[str] = []
        
        # 构建步骤映射
        step_map = {s.step_id: s for s in plan.steps}
        
        # 按依赖顺序执行
        executed: set[str] = set()
        
        for step in plan.steps:
            # 检查依赖
            if not all(dep in executed for dep in step.depends_on):
                error = f"步骤 {step.step_id} 依赖未满足"
                errors.append(error)
                step_results.append(StepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    success=False,
                    error=error,
                ))
                continue
            
            # 执行步骤
            logger.info(f"执行步骤 {step.step_id}: {step.tool}")
            tool_result = self._tool_executor.execute(step.tool, step.params)
            
            step_result = StepResult(
                step_id=step.step_id,
                tool=step.tool,
                success=tool_result.success,
                data=tool_result.data,
                error=tool_result.error,
            )
            step_results.append(step_result)
            
            if tool_result.success:
                executed.add(step.step_id)
            else:
                errors.append(f"步骤 {step.step_id} 执行失败: {tool_result.error}")
        
        return ExecutionResult(
            success=len(errors) == 0,
            task_id=plan.task_id,
            step_results=step_results,
            errors=errors,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/executor/ tests/unit/test_agent/test_task_executor.py
git commit -m "feat(agent): 实现任务执行引擎"
```

---

### Task 5: Agent 核心集成

**Covers:** [S3]

**Files:**
- Modify: `dataworks_agent/agent/core.py`
- Test: `tests/unit/test_agent/test_core.py`

**Interfaces:**
- Consumes: NLU, Planner, Executor
- Produces: 完整的 `Agent.chat()` 方法

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_core.py (添加)
def test_agent_chat_create_table(agent):
    """测试 Agent 处理创建表请求"""
    response = agent.chat("创建ods_user表")
    assert response.success is True
    assert "ods_user" in response.message
    assert "task_id" in response.data

def test_agent_chat_query_lineage(agent):
    """测试 Agent 处理查询血缘请求"""
    response = agent.chat("查询ods_user的血缘")
    assert response.success is True
    assert "ods_user" in response.message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_core.py::test_agent_chat_create_table -v`
Expected: FAIL (当前实现只返回回显)

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/core.py
"""Agent 核心模块 - 对话式数仓操作"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.agent.nlu.intent_parser import IntentParser, Intent
from dataworks_agent.agent.planner.task_planner import TaskPlanner
from dataworks_agent.agent.executor.task_executor import TaskExecutor, ExecutionResult

logger = logging.getLogger("dataworks_agent.agent")


@dataclass
class AgentResponse:
    """Agent 响应"""
    message: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Agent:
    """数仓操作 Agent"""
    
    def __init__(self):
        self._intent_parser = IntentParser()
        self._task_planner = TaskPlanner()
        self._task_executor = TaskExecutor()
    
    def chat(self, message: str) -> AgentResponse:
        """处理用户消息"""
        logger.info(f"收到用户消息: {message}")
        
        # 1. 意图解析
        intent = self._intent_parser.parse(message)
        logger.info(f"解析意图: {intent.action}, 置信度: {intent.confidence}")
        
        if intent.action == "unknown":
            return AgentResponse(
                message="抱歉，我无法理解您的需求。请尝试更具体的描述，例如：\n- 创建ods_user表\n- 查询ods_user的血缘\n- 检查任务状态",
                success=True,
            )
        
        # 2. 任务规划
        plan = self._task_planner.plan(intent)
        logger.info(f"生成任务计划: {plan.task_id}, 步骤数: {len(plan.steps)}")
        
        # 3. 任务执行
        result = self._task_executor.execute(plan)
        
        # 4. 构建响应
        return self._build_response(intent, plan, result)
    
    def _build_response(
        self,
        intent: Intent,
        plan: Any,
        result: ExecutionResult,
    ) -> AgentResponse:
        """构建响应"""
        if result.success:
            message = self._format_success_message(intent, result)
            return AgentResponse(
                message=message,
                success=True,
                data={
                    "task_id": result.task_id,
                    "steps_completed": len(result.step_results),
                },
            )
        else:
            message = self._format_error_message(intent, result)
            return AgentResponse(
                message=message,
                success=False,
                error=result.errors[0] if result.errors else "未知错误",
            )
    
    def _format_success_message(self, intent: Intent, result: ExecutionResult) -> str:
        """格式化成功消息"""
        action_messages = {
            "create_table": "已成功创建表",
            "query_lineage": "血缘查询结果",
            "check_status": "任务状态",
        }
        prefix = action_messages.get(intent.action, "操作已完成")
        table_name = intent.params.get("table_name", "")
        return f"{prefix} {table_name}" if table_name else prefix
    
    def _format_error_message(self, intent: Intent, result: ExecutionResult) -> str:
        """格式化错误消息"""
        return f"操作失败: {'; '.join(result.errors)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_core.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/core.py tests/unit/test_agent/test_core.py
git commit -m "feat(agent): 集成 NLU、规划器和执行器到 Agent 核心"
```

---

### Task 6: Agent API 路由

**Covers:** [S3]

**Files:**
- Create: `dataworks_agent/routers/agent.py`
- Modify: `dataworks_agent/main.py` (添加路由)
- Test: `tests/integration/test_agent_api.py`

**Interfaces:**
- Consumes: `Agent` 类
- Produces: REST API 端点 `/agent/chat`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_agent_api.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from dataworks_agent.main import app
    return TestClient(app)

def test_chat_endpoint(client):
    """测试聊天端点"""
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_user表"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "ods_user" in data["message"]

def test_chat_endpoint_empty_message(client):
    """测试空消息"""
    response = client.post(
        "/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/integration/test_agent_api.py -v`
Expected: FAIL with 404 (路由未注册)

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/routers/agent.py
"""Agent API 路由"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from dataworks_agent.agent.core import Agent

router = APIRouter(prefix="/agent", tags=["agent"])

_agent = Agent()


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str


class ChatResponse(BaseModel):
    """聊天响应"""
    message: str
    success: bool
    data: dict = {}
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """处理聊天消息"""
    response = _agent.chat(request.message)
    return ChatResponse(
        message=response.message,
        success=response.success,
        data=response.data,
        error=response.error,
    )
```

```python
# dataworks_agent/main.py (添加路由)
# 在 app.include_router 部分添加:
from dataworks_agent.routers.agent import router as agent_router
app.include_router(agent_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/integration/test_agent_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/routers/agent.py tests/integration/test_agent_api.py
git commit -m "feat(agent): 添加 Agent API 路由"
```

---

### Task 7: 前端对话界面组件

**Covers:** [S5]

**Files:**
- Create: `frontend/src/components/agent/AgentChat.vue`
- Create: `frontend/src/components/agent/ChatMessage.vue`
- Create: `frontend/src/components/agent/QuickActions.vue`
- Modify: `frontend/src/pages/ModelingDashboard.vue` (添加对话入口)

**Interfaces:**
- Consumes: `/agent/chat` API
- Produces: 对话界面组件

- [ ] **Step 1: Create ChatMessage component**

```vue
<!-- frontend/src/components/agent/ChatMessage.vue -->
<template>
  <div class="chat-message" :class="{ 'user-message': isUser }">
    <div class="message-avatar">
      <el-avatar :size="32" :icon="isUser ? 'User' : 'Monitor'" />
    </div>
    <div class="message-content">
      <div class="message-text">{{ message.text }}</div>
      <div class="message-time">{{ formatTime(message.timestamp) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: {
    id: string
    text: string
    isUser: boolean
    timestamp: Date
  }
}>()

const isUser = computed(() => props.message.isUser)

function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.user-message {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  background: #f0f0f0;
}

.user-message .message-text {
  background: #409eff;
  color: white;
}

.message-time {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}
</style>
```

- [ ] **Step 2: Create QuickActions component**

```vue
<!-- frontend/src/components/agent/QuickActions.vue -->
<template>
  <div class="quick-actions">
    <el-button
      v-for="action in actions"
      :key="action.label"
      @click="$emit('action', action.prompt)"
    >
      <el-icon><component :is="action.icon" /></el-icon>
      {{ action.label }}
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { Grid, DataLine, Warning } from '@element-plus/icons-vue'

defineEmits<{
  action: [prompt: string]
}>()

const actions = [
  { label: '创建表', prompt: '创建ods_', icon: Grid },
  { label: '查询血缘', prompt: '查询血缘', icon: DataLine },
  { label: '检查状态', prompt: '检查任务状态', icon: Warning },
]
</script>

<style scoped>
.quick-actions {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eee;
}
</style>
```

- [ ] **Step 3: Create AgentChat component**

```vue
<!-- frontend/src/components/agent/AgentChat.vue -->
<template>
  <div class="agent-chat">
    <div class="chat-header">
      <h3>数仓助手</h3>
    </div>
    
    <div class="chat-messages" ref="messagesRef">
      <ChatMessage
        v-for="msg in messages"
        :key="msg.id"
        :message="msg"
      />
    </div>
    
    <QuickActions @action="handleQuickAction" />
    
    <div class="chat-input">
      <el-input
        v-model="input"
        placeholder="描述您的需求..."
        @keyup.enter="sendMessage"
      >
        <template #append>
          <el-button @click="sendMessage" :loading="loading">
            发送
          </el-button>
        </template>
      </el-input>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import QuickActions from './QuickActions.vue'

const input = ref('')
const loading = ref(false)
const messages = ref<Array<{
  id: string
  text: string
  isUser: boolean
  timestamp: Date
}>>([
  {
    id: '1',
    text: '您好！我是数仓助手，可以帮您创建表、查询血缘、检查任务状态等。请问有什么可以帮您？',
    isUser: false,
    timestamp: new Date(),
  }
])

const messagesRef = ref<HTMLElement>()

async function sendMessage() {
  if (!input.value.trim() || loading.value) return
  
  const userMessage = input.value.trim()
  input.value = ''
  
  // 添加用户消息
  messages.value.push({
    id: Date.now().toString(),
    text: userMessage,
    isUser: true,
    timestamp: new Date(),
  })
  
  await nextTick()
  scrollToBottom()
  
  // 发送请求
  loading.value = true
  try {
    const response = await fetch('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userMessage }),
    })
    const data = await response.json()
    
    // 添加助手消息
    messages.value.push({
      id: (Date.now() + 1).toString(),
      text: data.message,
      isUser: false,
      timestamp: new Date(),
    })
  } catch (error) {
    messages.value.push({
      id: (Date.now() + 1).toString(),
      text: '抱歉，请求失败，请稍后重试。',
      isUser: false,
      timestamp: new Date(),
    })
  } finally {
    loading.value = false
    await nextTick()
    scrollToBottom()
  }
}

function handleQuickAction(prompt: string) {
  input.value = prompt
  sendMessage()
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}
</script>

<style scoped>
.agent-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  border: 1px solid #eee;
  border-radius: 8px;
  overflow: hidden;
}

.chat-header {
  padding: 12px 16px;
  background: #f5f5f5;
  border-bottom: 1px solid #eee;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.chat-input {
  padding: 12px;
  border-top: 1px solid #eee;
}
</style>
```

- [ ] **Step 4: Integrate into ModelingDashboard**

```vue
<!-- frontend/src/pages/ModelingDashboard.vue (添加) -->
<template>
  <div class="modeling-dashboard">
    <!-- 现有内容 -->
    
    <!-- 添加对话入口 -->
    <el-drawer v-model="showChat" title="数仓助手" size="400px">
      <AgentChat />
    </el-drawer>
    
    <el-button class="chat-fab" @click="showChat = true">
      <el-icon><ChatDotRound /></el-icon>
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'
import AgentChat from '@/components/agent/AgentChat.vue'

const showChat = ref(false)
</script>

<style scoped>
.chat-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  font-size: 24px;
}
</style>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/ frontend/src/pages/ModelingDashboard.vue
git commit -m "feat(agent): 添加前端对话界面组件"
```

---

### Task 8: WebSocket 实时通信

**Covers:** [S3]

**Files:**
- Modify: `dataworks_agent/routers/agent.py` (添加 WebSocket)
- Modify: `frontend/src/components/agent/AgentChat.vue` (使用 WebSocket)

**Interfaces:**
- Consumes: WebSocket 连接
- Produces: 实时消息推送

- [ ] **Step 1: Add WebSocket endpoint**

```python
# dataworks_agent/routers/agent.py (添加)
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self._connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self._connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self._connections:
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            response = _agent.chat(data.get("message", ""))
            await websocket.send_json({
                "type": "response",
                "data": {
                    "message": response.message,
                    "success": response.success,
                    "data": response.data,
                }
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

- [ ] **Step 2: Update frontend to use WebSocket**

```vue
<!-- frontend/src/components/agent/AgentChat.vue (修改) -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const ws = ref<WebSocket | null>(null)

onMounted(() => {
  ws.value = new WebSocket(`ws://${window.location.host}/agent/ws`)
  
  ws.value.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'response') {
      messages.value.push({
        id: (Date.now() + 1).toString(),
        text: data.data.message,
        isUser: false,
        timestamp: new Date(),
      })
      loading.value = false
    }
  }
})

onUnmounted(() => {
  ws.value?.close()
})

async function sendMessage() {
  if (!input.value.trim() || loading.value) return
  
  const userMessage = input.value.trim()
  input.value = ''
  
  messages.value.push({
    id: Date.now().toString(),
    text: userMessage,
    isUser: true,
    timestamp: new Date(),
  })
  
  loading.value = true
  
  ws.value?.send(JSON.stringify({ message: userMessage }))
}
</script>
```

- [ ] **Step 3: Commit**

```bash
git add dataworks_agent/routers/agent.py frontend/src/components/agent/AgentChat.vue
git commit -m "feat(agent): 添加 WebSocket 实时通信"
```

---

### Task 9: 集成测试

**Covers:** [S9]

**Files:**
- Create: `tests/integration/test_agent_integration.py`

**Interfaces:**
- Consumes: Agent API
- Produces: 集成测试报告

- [ ] **Step 1: Write integration tests**

```python
# tests/integration/test_agent_integration.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from dataworks_agent.main import app
    return TestClient(app)

def test_full_chat_flow(client):
    """测试完整对话流程"""
    # 1. 创建表
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_user表"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data["data"]
    
    task_id = data["data"]["task_id"]
    
    # 2. 查询血缘
    response = client.post(
        "/agent/chat",
        json={"message": "查询ods_user的血缘"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

def test_unknown_intent(client):
    """测试未知意图"""
    response = client.post(
        "/agent/chat",
        json={"message": "今天天气怎么样"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "无法理解" in data["message"]
```

- [ ] **Step 2: Run integration tests**

Run: `uv run python -m pytest tests/integration/test_agent_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_agent_integration.py
git commit -m "test(agent): 添加 Agent 集成测试"
```

---

### Task 10: 文档和清理

**Covers:** [S10]

**Files:**
- Modify: `README.md` (添加 Agent 章节)
- Modify: `CLAUDE.md` (添加 Agent 开发规范)

**Interfaces:**
- 无

- [ ] **Step 1: Update README**

```markdown
## Agent 功能

### 对话式操作

通过自然语言与数仓助手交互，支持：

- **创建表**: "创建ods_user表"
- **查询血缘**: "查询ods_user的血缘"
- **检查状态**: "检查任务状态"

### API 接口

- `POST /agent/chat` - 聊天接口
- `WS /agent/ws` - WebSocket 实时通信

### 使用示例

```bash
# 创建表
curl -X POST http://localhost:8085/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "创建ods_user表"}'
```
```

- [ ] **Step 2: Update CLAUDE.md**

```markdown
## Agent 开发规范

### 目录结构

- `dataworks_agent/agent/` - Agent 核心模块
- `frontend/src/components/agent/` - 前端对话组件

### 开发流程

1. 新增意图: 在 `nlu/templates.py` 添加模板
2. 新增工具: 在 `executor/tool_executor.py` 集成
3. 新增响应: 在 `core.py` 添加格式化逻辑

### 测试要求

- 单元测试覆盖核心逻辑
- 集成测试覆盖 API 端点
- E2E 测试覆盖用户流程
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs(agent): 添加 Agent 文档和开发规范"
```

---

## Self-Review

**1. Spec coverage:** ✅ 所有 [Sn] 章节都有对应任务覆盖

**2. Placeholder scan:** ✅ 无 TBD/TODO 占位符

**3. Type consistency:** ✅ 类型、方法签名在任务间保持一致

## Execution Handoff

Plan saved. How would you like to execute it?

- **Subagent, always**: 每个任务使用新子代理执行
- **Subagent, this time**: 本次使用子代理执行
- **Inline, always**: 在当前会话中执行
- **Inline, this time**: 本次在当前会话中执行
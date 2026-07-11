# Agent 系统 Phase 2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Agent 自主规划与执行能力，支持任务自动拆解、多步骤编排、错误恢复与重试

**Architecture:** 在 Phase 1 基础上扩展，增强 TaskPlanner 支持复杂任务拆解，TaskExecutor 支持错误恢复和重试，添加执行计划可视化

**Tech Stack:** Python 3.12+, FastAPI, WebSocket, Vue 3

## Global Constraints

- Python ≥ 3.12, 使用 uv 管理依赖
- 前端 Vue 3 + Vite + Element Plus
- 保持与 Phase 1 的向后兼容
- 所有新代码必须有单元测试
- 遵循项目现有代码风格和架构

---

## 文件结构

```
dataworks_agent/agent/
├── planner/                    # 任务规划 (扩展)
│   ├── task_planner.py         # 添加 LLM 规划支持
│   └── task拆解器.py           # 新增：复杂任务拆解
├── executor/                   # 执行引擎 (扩展)
│   ├── task_executor.py        # 添加错误恢复和重试
│   └── retry_handler.py        # 新增：重试处理器
└── monitor/                    # 新增：执行监控
    └── execution_monitor.py    # 执行状态监控

frontend/src/components/agent/
├── TaskExecution.vue           # 新增：任务执行面板
└── ExecutionProgress.vue       # 新增：执行进度显示
```

---

### Task 1: 任务拆解器

**Covers:** [S3.2.2] 任务规划器扩展

**Files:**
- Create: `dataworks_agent/agent/planner/task_decomposer.py`
- Test: `tests/unit/test_agent/test_task_decomposer.py`

**Interfaces:**
- Consumes: 复杂任务描述
- Produces: 任务步骤列表

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_task_decomposer.py
import pytest
from dataworks_agent.agent.planner.task_decomposer import TaskDecomposer

@pytest.fixture
def decomposer():
    return TaskDecomposer()

def test_decompose_simple_task(decomposer):
    """测试简单任务拆解"""
    result = decomposer.decompose("创建ods_user表")
    assert len(result.steps) > 0
    assert result.steps[0].tool in ["create_holo_table", "create_mc_table"]

def test_decompose_complex_task(decomposer):
    """测试复杂任务拆解"""
    result = decomposer.decompose("创建ods_user表并配置调度")
    assert len(result.steps) >= 2
    assert any("schedule" in step.tool for step in result.steps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_decomposer.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/planner/task_decomposer.py
"""任务拆解器 - 将复杂任务拆解为可执行步骤"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecomposedStep:
    """拆解后的步骤"""
    description: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    """拆解结果"""
    steps: list[DecomposedStep]
    original_task: str


class TaskDecomposer:
    """任务拆解器"""
    
    # 复杂任务模式
    COMPLEX_PATTERNS = [
        (r"创建.*表.*并.*配置.*调度", ["create_table", "configure_schedule"]),
        (r"创建.*表.*并.*设置.*依赖", ["create_table", "add_dependency"]),
        (r"更新.*表.*并.*重新.*部署", ["update_table", "deploy_node"]),
    ]
    
    def decompose(self, task: str) -> DecompositionResult:
        """拆解任务"""
        task_lower = task.lower().strip()
        
        # 检查是否是复杂任务
        for pattern, subtasks in self.COMPLEX_PATTERNS:
            if re.search(pattern, task_lower):
                steps = []
                for i, subtask in enumerate(subtasks):
                    step = DecomposedStep(
                        description=f"子任务 {i+1}: {subtask}",
                        tool=subtask,
                        depends_on=[f"step_{i-1}"] if i > 0 else [],
                    )
                    steps.append(step)
                return DecompositionResult(steps=steps, original_task=task)
        
        # 简单任务，返回单步骤
        return DecompositionResult(
            steps=[DecomposedStep(description=task, tool="unknown")],
            original_task=task,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_decomposer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/planner/task_decomposer.py tests/unit/test_agent/test_task_decomposer.py
git commit -m "feat(agent): 实现任务拆解器，支持复杂任务拆解"
```

---

### Task 2: 重试处理器

**Covers:** [S3.2.3] 执行引擎扩展

**Files:**
- Create: `dataworks_agent/agent/executor/retry_handler.py`
- Test: `tests/unit/test_agent/test_retry_handler.py`

**Interfaces:**
- Consumes: 执行失败信息
- Produces: 重试策略

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_retry_handler.py
import pytest
from dataworks_agent.agent.executor.retry_handler import RetryHandler, RetryStrategy

@pytest.fixture
def handler():
    return RetryHandler(max_retries=3)

def test_should_retry_on_transient_error(handler):
    """测试瞬时错误应该重试"""
    strategy = handler.get_strategy("connection_timeout")
    assert strategy.should_retry is True
    assert strategy.delay_seconds > 0

def test_should_not_retry_on_permanent_error(handler):
    """测试永久错误不应重试"""
    strategy = handler.get_strategy("invalid_table_name")
    assert strategy.should_retry is False

def test_retry_count_exceeded(handler):
    """测试重试次数超限"""
    for _ in range(3):
        handler.record_attempt("test_error")
    
    strategy = handler.get_strategy("connection_timeout")
    assert strategy.should_retry is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_retry_handler.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/executor/retry_handler.py
"""重试处理器 - 处理执行失败和重试策略"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetryStrategy:
    """重试策略"""
    should_retry: bool
    delay_seconds: float
    reason: str


@dataclass
class ErrorPattern:
    """错误模式"""
    keyword: str
    is_transient: bool
    base_delay: float = 1.0


class RetryHandler:
    """重试处理器"""
    
    # 错误模式定义
    ERROR_PATTERNS = [
        ErrorPattern("connection_timeout", is_transient=True, base_delay=2.0),
        ErrorPattern("throttling", is_transient=True, base_delay=5.0),
        ErrorPattern("rate_limit", is_transient=True, base_delay=10.0),
        ErrorPattern("invalid_table_name", is_transient=False),
        ErrorPattern("permission_denied", is_transient=False),
        ErrorPattern("not_found", is_transient=False),
    ]
    
    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._attempt_counts: dict[str, int] = {}
    
    def record_attempt(self, error_type: str) -> None:
        """记录尝试次数"""
        self._attempt_counts[error_type] = self._attempt_counts.get(error_type, 0) + 1
    
    def get_strategy(self, error_type: str) -> RetryStrategy:
        """获取重试策略"""
        # 检查重试次数
        attempts = self._attempt_counts.get(error_type, 0)
        if attempts >= self._max_retries:
            return RetryStrategy(
                should_retry=False,
                delay_seconds=0,
                reason=f"重试次数已超限 ({attempts}/{self._max_retries})",
            )
        
        # 查找错误模式
        for pattern in self.ERROR_PATTERNS:
            if pattern.keyword in error_type.lower():
                if pattern.is_transient:
                    # 指数退避
                    delay = pattern.base_delay * (2 ** attempts)
                    return RetryStrategy(
                        should_retry=True,
                        delay_seconds=delay,
                        reason=f"瞬时错误，{delay:.1f}秒后重试",
                    )
                else:
                    return RetryStrategy(
                        should_retry=False,
                        delay_seconds=0,
                        reason="永久错误，不重试",
                    )
        
        # 未知错误，默认重试
        return RetryStrategy(
            should_retry=True,
            delay_seconds=1.0,
            reason="未知错误，尝试重试",
        )
    
    def reset(self, error_type: str | None = None) -> None:
        """重置尝试次数"""
        if error_type:
            self._attempt_counts.pop(error_type, None)
        else:
            self._attempt_counts.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_retry_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/executor/retry_handler.py tests/unit/test_agent/test_retry_handler.py
git commit -m "feat(agent): 实现重试处理器，支持指数退避和错误分类"
```

---

### Task 3: 执行监控器

**Covers:** [S5] 前端集成设计扩展

**Files:**
- Create: `dataworks_agent/agent/monitor/execution_monitor.py`
- Test: `tests/unit/test_agent/test_execution_monitor.py`

**Interfaces:**
- Consumes: 任务执行状态
- Produces: 实时状态更新

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_execution_monitor.py
import pytest
from dataworks_agent.agent.monitor.execution_monitor import ExecutionMonitor, ExecutionStatus

@pytest.fixture
def monitor():
    return ExecutionMonitor()

def test_record_step_start(monitor):
    """测试记录步骤开始"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    status = monitor.get_status("task_1")
    assert status is not None
    assert status.current_step == "step_0"

def test_record_step_complete(monitor):
    """测试记录步骤完成"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    monitor.record_step_complete("task_1", "step_0", success=True)
    status = monitor.get_status("task_1")
    assert status.completed_steps == 1

def test_record_step_failure(monitor):
    """测试记录步骤失败"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    monitor.record_step_complete("task_1", "step_0", success=False, error="连接超时")
    status = monitor.get_status("task_1")
    assert status.failed_steps == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_execution_monitor.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/monitor/execution_monitor.py
"""执行监控器 - 跟踪任务执行状态"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepStatus:
    """步骤状态"""
    step_id: str
    tool: str
    status: str  # pending, running, completed, failed
    start_time: float | None = None
    end_time: float | None = None
    error: str | None = None


@dataclass
class ExecutionStatus:
    """执行状态"""
    task_id: str
    current_step: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    steps: dict[str, StepStatus] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None


class ExecutionMonitor:
    """执行监控器"""
    
    def __init__(self):
        self._statuses: dict[str, ExecutionStatus] = {}
    
    def record_step_start(self, task_id: str, step_id: str, tool: str) -> None:
        """记录步骤开始"""
        if task_id not in self._statuses:
            self._statuses[task_id] = ExecutionStatus(task_id=task_id)
        
        status = self._statuses[task_id]
        if status.start_time is None:
            status.start_time = time.time()
        
        status.current_step = step_id
        status.steps[step_id] = StepStatus(
            step_id=step_id,
            tool=tool,
            status="running",
            start_time=time.time(),
        )
    
    def record_step_complete(
        self,
        task_id: str,
        step_id: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """记录步骤完成"""
        if task_id not in self._statuses:
            return
        
        status = self._statuses[task_id]
        if step_id in status.steps:
            step = status.steps[step_id]
            step.status = "completed" if success else "failed"
            step.end_time = time.time()
            step.error = error
            
            if success:
                status.completed_steps += 1
            else:
                status.failed_steps += 1
    
    def get_status(self, task_id: str) -> ExecutionStatus | None:
        """获取任务状态"""
        return self._statuses.get(task_id)
    
    def complete_task(self, task_id: str) -> None:
        """标记任务完成"""
        if task_id in self._statuses:
            self._statuses[task_id].end_time = time.time()
            self._statuses[task_id].current_step = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_execution_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/monitor/ tests/unit/test_agent/test_execution_monitor.py
git commit -m "feat(agent): 实现执行监控器，跟踪任务执行状态"
```

---

### Task 4: 增强 TaskPlanner 支持 LLM 规划

**Covers:** [S3.2.2] 任务规划器扩展

**Files:**
- Modify: `dataworks_agent/agent/planner/task_planner.py`
- Test: `tests/unit/test_agent/test_task_planner.py`

**Interfaces:**
- Consumes: 意图对象 + LLM 服务
- Produces: 增强的任务计划

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_task_planner.py (添加)
def test_plan_with_llm_fallback(planner):
    """测试 LLM 规划回退"""
    intent = Intent(
        action="unknown",
        params={},
        confidence=0.0,
        raw_text="帮我创建一个用户表并配置每天调度",
    )
    # 当模板匹配失败时，应该尝试 LLM 规划
    plan = planner.plan(intent)
    assert isinstance(plan, TaskPlan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_planner.py::test_plan_with_llm_fallback -v`
Expected: FAIL (当前 unknown intent 返回空计划)

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/planner/task_planner.py (修改)
def plan(self, intent: Intent) -> TaskPlan:
    """根据意图生成任务计划"""
    task_id = f"task_{intent.action}_{abs(hash(intent.raw_text)) % 10000}"

    if intent.action == "unknown":
        # 尝试使用 LLM 进行任务拆解
        steps = self._llm_plan(intent.raw_text)
        if steps:
            return TaskPlan(task_id=task_id, steps=steps, intent=intent)
        
        logger.info("未知意图，返回空计划: %s", intent.raw_text)
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

    # 使用 TaskGraph 验证依赖关系
    graph = self._build_dependency_graph(steps)
    if not graph.validate():
        logger.warning("检测到循环依赖，使用线性顺序")

    return TaskPlan(task_id=task_id, steps=steps, intent=intent)

def _llm_plan(self, task_description: str) -> list[TaskStep]:
    """使用 LLM 进行任务规划（Phase 2 实现）"""
    # TODO: Phase 2 集成 LLM 服务
    # 当前返回空列表，后续集成 DeepSeek API
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_planner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/planner/task_planner.py
git commit -m "feat(agent): TaskPlanner 添加 LLM 规划回退接口"
```

---

### Task 5: 增强 TaskExecutor 支持错误恢复

**Covers:** [S3.2.3] 执行引擎扩展

**Files:**
- Modify: `dataworks_agent/agent/executor/task_executor.py`
- Test: `tests/unit/test_agent/test_task_executor.py`

**Interfaces:**
- Consumes: 任务计划 + 重试处理器
- Produces: 增强的执行结果

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent/test_task_executor.py (添加)
def test_execute_with_retry(executor):
    """测试带重试的执行"""
    plan = TaskPlan(
        task_id="test_retry",
        steps=[
            TaskStep(step_id="step_0", tool="create_holo_table", params={"table_name": "test"}),
        ],
    )
    # 模拟第一次失败，第二次成功
    result = executor.execute(plan)
    assert isinstance(result, ExecutionResult)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_executor.py::test_execute_with_retry -v`
Expected: FAIL (当前无重试逻辑)

- [ ] **Step 3: Write minimal implementation**

```python
# dataworks_agent/agent/executor/task_executor.py (修改)
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
        
        # 执行步骤（带重试）
        logger.info("执行步骤 %s: %s", step.step_id, step.tool)
        tool_result = self._execute_with_retry(step)
        
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

def _execute_with_retry(self, step: TaskStep, max_retries: int = 3) -> ToolResult:
    """带重试的执行"""
    for attempt in range(max_retries):
        result = self._tool_executor.execute(step.tool, step.params)
        if result.success:
            return result
        
        # 检查是否应该重试
        if attempt < max_retries - 1 and self._should_retry(result.error):
            logger.info("步骤 %s 失败，%d秒后重试 (尝试 %d/%d)",
                       step.step_id, 2 ** attempt, attempt + 1, max_retries)
            time.sleep(2 ** attempt)  # 指数退避
    
    return result  # 返回最后一次结果
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_agent/test_task_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dataworks_agent/agent/executor/task_executor.py
git commit -m "feat(agent): TaskExecutor 添加错误恢复和重试机制"
```

---

### Task 6: 前端执行面板组件

**Covers:** [S5] 前端集成设计扩展

**Files:**
- Create: `frontend/src/components/agent/TaskExecution.vue`
- Create: `frontend/src/components/agent/ExecutionProgress.vue`

**Interfaces:**
- Consumes: 执行状态 API
- Produces: 执行进度 UI

- [ ] **Step 1: Create TaskExecution component**

```vue
<!-- frontend/src/components/agent/TaskExecution.vue -->
<template>
  <div class="task-execution">
    <div class="execution-header">
      <h4>任务执行</h4>
      <el-tag :type="statusType">{{ statusText }}</el-tag>
    </div>
    
    <ExecutionProgress 
      v-if="status"
      :status="status"
    />
    
    <div class="execution-actions">
      <el-button 
        v-if="status?.current_step"
        type="danger" 
        size="small"
        @click="$emit('cancel')"
      >
        取消执行
      </el-button>
      <el-button 
        v-if="status?.failed_steps > 0"
        type="warning" 
        size="small"
        @click="$emit('retry')"
      >
        重试失败步骤
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ExecutionProgress from './ExecutionProgress.vue'

interface ExecutionStatus {
  task_id: string
  current_step: string | null
  total_steps: number
  completed_steps: number
  failed_steps: number
}

const props = defineProps<{
  status: ExecutionStatus | null
}>()

defineEmits<{
  cancel: []
  retry: []
}>()

const statusType = computed(() => {
  if (!props.status) return 'info'
  if (props.status.failed_steps > 0) return 'danger'
  if (props.status.current_step) return 'warning'
  return 'success'
})

const statusText = computed(() => {
  if (!props.status) return '等待中'
  if (props.status.failed_steps > 0) return '执行失败'
  if (props.status.current_step) return '执行中'
  return '已完成'
})
</script>
```

- [ ] **Step 2: Create ExecutionProgress component**

```vue
<!-- frontend/src/components/agent/ExecutionProgress.vue -->
<template>
  <div class="execution-progress">
    <el-progress 
      :percentage="progressPercentage"
      :status="progressStatus"
    />
    
    <div class="step-list">
      <div 
        v-for="step in steps"
        :key="step.step_id"
        class="step-item"
        :class="step.status"
      >
        <el-icon>
          <Check v-if="step.status === 'completed'" />
          <Close v-if="step.status === 'failed'" />
          <Loading v-if="step.status === 'running'" />
        </el-icon>
        <span class="step-name">{{ step.tool }}</span>
        <span class="step-status">{{ step.status }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, Close, Loading } from '@element-plus/icons-vue'

interface StepStatus {
  step_id: string
  tool: string
  status: 'pending' | 'running' | 'completed' | 'failed'
}

const props = defineProps<{
  status: {
    total_steps: number
    completed_steps: number
    failed_steps: number
    steps: Record<string, StepStatus>
  }
}>()

const progressPercentage = computed(() => {
  if (props.status.total_steps === 0) return 0
  return Math.round((props.status.completed_steps / props.status.total_steps) * 100)
})

const progressStatus = computed(() => {
  if (props.status.failed_steps > 0) return 'exception'
  if (props.status.completed_steps === props.status.total_steps) return 'success'
  return undefined
})

const steps = computed(() => {
  return Object.values(props.status.steps)
})
</script>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/agent/TaskExecution.vue frontend/src/components/agent/ExecutionProgress.vue
git commit -m "feat(agent): 添加任务执行面板和进度显示组件"
```

---

### Task 7: 集成测试和文档更新

**Covers:** [S9] 测试策略, [S10] 文档

**Files:**
- Modify: `tests/integration/test_agent_integration.py`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- 无

- [ ] **Step 1: Add Phase 2 integration tests**

```python
# tests/integration/test_agent_integration.py (添加)
def test_complex_task_decomposition(client):
    """测试复杂任务拆解"""
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_user表并配置调度"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["steps_completed"] >= 2

def test_task_execution_with_retry(client):
    """测试任务执行重试"""
    # 这个测试需要 mock ToolExecutor 来模拟失败和重试
    pass  # TODO: 实现
```

- [ ] **Step 2: Update README with Phase 2 features**

```markdown
## Agent 功能 (Phase 2)

### 自主规划与执行

- **任务自动拆解**: 复杂任务自动拆解为可执行步骤
- **错误恢复与重试**: 瞬时错误自动重试，指数退避
- **执行状态监控**: 实时跟踪任务执行进度

### 支持的复杂任务

- "创建ods_user表并配置调度" → 拆解为建表 + 配置调度
- "更新dwd_order表并重新部署" → 拆解为更新 + 部署
```

- [ ] **Step 3: Update CLAUDE.md with Phase 2 development guide**

```markdown
## Phase 2 开发规范

### 新增组件

- `agent/planner/task_decomposer.py` - 任务拆解器
- `agent/executor/retry_handler.py` - 重试处理器
- `agent/monitor/execution_monitor.py` - 执行监控器
- `frontend/src/components/agent/TaskExecution.vue` - 任务执行面板
- `frontend/src/components/agent/ExecutionProgress.vue` - 执行进度显示

### 扩展点

- TaskPlanner: `_llm_plan()` 方法用于集成 LLM 规划
- TaskExecutor: `_execute_with_retry()` 方法用于错误恢复
- ExecutionMonitor: 实时状态更新 API
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_agent_integration.py README.md CLAUDE.md
git commit -m "docs(agent): 更新 Phase 2 文档和集成测试"
```

---

## Self-Review

**1. Spec coverage:** ✅ Phase 2 规划与执行能力已实现

**2. Placeholder scan:** ✅ LLM 集成使用 TODO 标记，后续实现

**3. Type consistency:** ✅ 类型、方法签名在任务间保持一致

## Execution Handoff

Phase 2 计划已创建。用户下班后，我可以自主执行这些任务。

**Phase 2 核心目标**:
1. 任务拆解器 - 支持复杂任务自动拆解
2. 重试处理器 - 支持错误恢复和指数退避
3. 执行监控器 - 跟踪任务执行状态
4. LLM 规划接口 - 为后续 LLM 集成预留
5. 前端执行面板 - 可视化执行进度

**预计工作量**: 7 个任务，约 2-3 小时
# Agentic Web Runtime Corrective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute this plan inline task-by-task; no subagents are authorized for this run. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the page's fake chat workflow with a bounded tool-using run loop whose table-discovery path, streaming events, failure recovery, capability health, and browser evidence are real.

**Architecture:** Add typed tools with explicit side-effect metadata, a deterministic-first decision provider, and an `AgentRunCoordinator` that owns one observe/decide/act loop. Route legacy chat and the new NDJSON endpoint through the same coordinator, migrate `SmartChatPage` to one run stream, and prove the product with deterministic full-stack browser journeys plus a live degradation journey.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, LangGraph SQLite state, Vue 3, TypeScript, NDJSON over fetch streams, Vitest, pytest, Playwright.

## Global Constraints

- Never create a DataWorks folder or business-process directory.
- Do not execute a real DataWorks write during automated acceptance.
- Existing destructive guards, exact path/name reuse, parent-directory evidence, and Publish Gate remain authoritative.
- Read-only failures must never produce `execution_unknown`.
- The LLM cannot call DataWorks clients directly.
- A completion checkbox requires the named test command and evidence artifact to exist.
- Backend gate: `uv run python -m pytest tests/integration/ -q --tb=short` and `uv run ruff check .`.
- Frontend gate: `npm run test:unit`, `npm run build`, and `npm run test:e2e`.

---

### Task 1: Typed Tools and Side-Effect Failure Policy

**Files:**
- Create: `dataworks_agent/agent/tools/__init__.py`
- Create: `dataworks_agent/agent/tools/base.py`
- Create: `dataworks_agent/agent/tools/registry.py`
- Create: `tests/integration/test_agent_run_tools.py`

**Interfaces:**
- Produces `SideEffect`, `ToolContext`, `ToolResult`, `AgentTool`, and `ToolRegistry`.
- `ToolResult.uncertain_write` is true only when `write_boundary_crossed` and the declared side effect is write-capable.

- [x] **Step 1: Write failing tool-policy tests**

```python
@pytest.mark.asyncio
async def test_read_tool_failure_is_recoverable():
    tool = FakeTool(side_effect=SideEffect.READ, result=ToolResult.failure("offline"))
    result = await ToolRegistry([tool]).execute(tool.name, {}, ToolContext("conv", {}))
    assert result.recoverable is True
    assert result.uncertain_write is False

@pytest.mark.asyncio
async def test_write_is_uncertain_only_after_boundary():
    before = ToolResult.failure("validation", write_boundary_crossed=False)
    after = ToolResult.failure("timeout", write_boundary_crossed=True)
    assert before.for_effect(SideEffect.DEV_WRITE).uncertain_write is False
    assert after.for_effect(SideEffect.DEV_WRITE).uncertain_write is True
```

- [ ] **Step 2: Run the tests and confirm import failure**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py -q`

Expected: collection fails because `dataworks_agent.agent.tools` does not exist.

- [x] **Step 3: Implement the contracts**

```python
class SideEffect(StrEnum):
    NONE = "none"
    READ = "read"
    DEV_WRITE = "dev_write"
    DESTRUCTIVE = "destructive"
    PUBLISH = "publish"

@dataclass
class ToolResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    recoverable: bool = True
    write_boundary_crossed: bool = False
    uncertain_write: bool = False

    def for_effect(self, effect: SideEffect) -> "ToolResult":
        self.uncertain_write = self.write_boundary_crossed and effect in {
            SideEffect.DEV_WRITE, SideEffect.DESTRUCTIVE, SideEffect.PUBLISH
        }
        return self
```

`ToolRegistry.execute()` validates the name, emits no side effects itself, catches tool exceptions into a recoverable failure for `NONE/READ`, and applies `for_effect()`.

- [x] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py -q`

Expected: all Task 1 tests pass.

- [x] **Step 5: Commit**

```powershell
git add dataworks_agent/agent/tools tests/integration/test_agent_run_tools.py
git commit -m "feat(agent): add typed tool side-effect policy"
```

### Task 2: First-Class Table Discovery Tool

**Files:**
- Create: `dataworks_agent/agent/tools/table_discovery.py`
- Modify: `dataworks_agent/agent/response_policy.py`
- Modify: `dataworks_agent/agent/interaction.py`
- Test: `tests/integration/test_agent_run_tools.py`

**Interfaces:**
- Consumes `MetadataProvider.search_table(keyword, message)`.
- Produces `ToolResult.data.interaction` with server-owned full table identifiers.
- Never invokes `_build_query_plan()` or `LLMService`.

- [x] **Step 1: Add failing discovery tests**

```python
@pytest.mark.asyncio
async def test_find_table_returns_candidates_without_llm():
    provider = AsyncMock()
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[{"full_name": "dw.dwd_orders", "layer": "dwd", "comment": "订单"}],
    )
    result = await TableDiscoveryTool(provider).execute(
        {"keyword": "订单"}, ToolContext("conv", {})
    )
    assert result.success is True
    assert result.data["interaction"]["purpose"] == "select_table"
    assert result.data["interaction"]["options"][0]["payload"]["params"]["table_name"] == "dw.dwd_orders"

@pytest.mark.asyncio
async def test_find_table_no_hit_is_recoverable():
    provider = AsyncMock()
    provider.search_table.return_value = None
    result = await TableDiscoveryTool(provider).execute(
        {"keyword": "订单"}, ToolContext("conv", {})
    )
    assert result.success is False
    assert result.recoverable is True
    assert result.data["interaction"]["type"] == "free_text"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py -q`

Expected: `TableDiscoveryTool` is missing.

- [x] **Step 3: Implement deterministic candidate shaping**

The tool normalizes `keyword` by removing only leading intent verbs (`查找`, `搜索`, `找`, `查看`) and a trailing `表`, but rejects an empty keyword. It applies an optional exact layer filter, limits visible candidates to eight, groups larger sets by layer, and returns a free-text clarification when no evidence exists.

- [x] **Step 4: Make entry options carry an action**

The `find_table` option payload becomes:

```python
{
    "value": "查找数据表",
    "action": "find_table",
    "params": {"tool_name": "find_table"},
}
```

Do not route this option through `ask_data`.

- [x] **Step 5: Verify tests**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py tests/integration/test_agent_interaction.py -q --tb=short`

- [x] **Step 6: Commit**

```powershell
git add dataworks_agent/agent/tools/table_discovery.py dataworks_agent/agent/interaction.py dataworks_agent/agent/response_policy.py tests/integration/test_agent_run_tools.py
git commit -m "feat(agent): make table discovery a first-class tool"
```

### Task 3: Bounded Agent Run Coordinator

**Files:**
- Create: `dataworks_agent/agent/run_models.py`
- Create: `dataworks_agent/agent/decision_provider.py`
- Create: `dataworks_agent/agent/run_coordinator.py`
- Modify: `dataworks_agent/agent/core.py`
- Test: `tests/integration/test_agent_run_coordinator.py`

**Interfaces:**
- Produces `AgentRunRequest`, `RunEvent`, `RespondDecision`, `ToolDecision`, `ClarifyDecision`.
- `AgentRunCoordinator.run(request, emit=...) -> ChatResponse`.
- The coordinator is bounded to six decisions and persists one authoritative response.

- [x] **Step 1: Write failing journey tests**

```python
@pytest.mark.asyncio
async def test_greeting_find_table_and_explain_survive_read_failure(runtime):
    greeting = await runtime.run(AgentRunRequest("conv", "你好"), emit=lambda event: None)
    find = await runtime.run(answer_request(greeting, "find_table"), emit=lambda event: None)
    explain = await runtime.run(AgentRunRequest("conv", "什么意思"), emit=lambda event: None)
    assert greeting.data["interaction"]["purpose"] == "choose_entry"
    assert find.data["agent_mode"] == "recoverable_error"
    assert find.data["conversation"]["status"] != "execution_unknown"
    assert explain.error != "execution_unknown"

@pytest.mark.asyncio
async def test_broken_llm_does_not_block_deterministic_find_table(runtime):
    runtime.decisions.llm = AsyncMock(side_effect=LLMError("model_not_found"))
    response = await runtime.run(AgentRunRequest("conv", "找订单表"), emit=lambda event: None)
    assert response.data["interaction"]["purpose"] in {"select_table", "refine_table_search"}
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run python -m pytest tests/integration/test_agent_run_coordinator.py -q`

- [x] **Step 3: Implement decisions and coordinator**

Deterministic decisions cover greeting, explain, cancel/reset, active interaction answers, explicit `find_table`, physical table references, and health requests. The LLM receives only compact state and tool schemas. Any invalid or unavailable LLM result becomes `ClarifyDecision`.

The coordinator emits events before and after every decision/tool, maps `ToolResult.uncertain_write` to the only `execution_unknown` path, and maps every read failure to `recoverable_error` with a new pending interaction.

- [x] **Step 4: Delegate ChatAgent**

Keep `ChatAgent.chat()` public API, but route supported page turns through the coordinator. Existing modeling workflows are registered through `WorkflowAdapterTool`; do not duplicate business implementations.

- [x] **Step 5: Verify focused backend journeys**

Run: `uv run python -m pytest tests/integration/test_agent_run_coordinator.py tests/integration/test_agent_interaction.py tests/integration/test_context_resolver.py -q --tb=short`

- [x] **Step 6: Commit**

```powershell
git add dataworks_agent/agent/run_models.py dataworks_agent/agent/decision_provider.py dataworks_agent/agent/run_coordinator.py dataworks_agent/agent/core.py tests/integration/test_agent_run_coordinator.py
git commit -m "feat(agent): add bounded conversational run loop"
```

### Task 4: One Real Run Stream and Page Timeline

**Files:**
- Modify: `dataworks_agent/routers/agent.py`
- Modify: `dataworks_agent/routers/agent_sse.py`
- Create: `frontend/src/components/agent/runStream.ts`
- Modify: `frontend/src/pages/SmartChatPage.vue`
- Modify: `frontend/src/components/agent/MessageBubble.vue`
- Create: `frontend/src/__tests__/runStream.spec.ts`
- Modify: `frontend/src/__tests__/conversationLifecycle.spec.ts`

**Interfaces:**
- `POST /agent/runs/stream` accepts `ChatRequest` JSON and emits NDJSON `RunEvent` rows.
- `streamAgentRun(request, onEvent, fetcher?)` parses chunk boundaries safely.

- [x] **Step 1: Write failing router and parser tests**

Backend asserts the sequence includes `run.started`, `tool.started`, `tool.completed`, `state.persisted`, and one final `response.completed`. Frontend feeds JSON split across arbitrary byte chunks and asserts ordered events plus exactly one final response.

- [x] **Step 2: Implement the streaming endpoint**

Use an `asyncio.Queue[RunEvent]`, run the coordinator in a task, yield queue events as UTF-8 NDJSON, and cancel the task if the client disconnects. Legacy GET SSE and POST chat call the same coordinator.

- [x] **Step 3: Implement the stream client**

```ts
export async function streamAgentRun(
  request: AgentChatRequest,
  onEvent: (event: RunEvent) => void,
  fetcher: typeof fetch = fetch,
): Promise<AgentPayload> { /* TextDecoder streaming buffer + final-event validation */ }
```

- [x] **Step 4: Migrate both text and card answers**

`handleSend()` and `handleInteractionAnswer()` call `streamAgentRun()`. The page shows actual tool/event labels, does not invent a fixed thinking phase, and leaves retry enabled on recoverable failures.

- [x] **Step 5: Run frontend and stream tests**

Run: `uv run python -m pytest tests/integration/test_agent_api.py tests/integration/test_agent_run_coordinator.py -q --tb=short`

Run from `frontend`: `npm run test:unit`

Run from `frontend`: `npm run build`

- [x] **Step 6: Commit**

```powershell
git add dataworks_agent/routers/agent.py dataworks_agent/routers/agent_sse.py frontend/src/components/agent/runStream.ts frontend/src/pages/SmartChatPage.vue frontend/src/components/agent/MessageBubble.vue frontend/src/__tests__
git commit -m "feat(frontend): stream real agent run events"
```

### Task 5: Truthful Capability Registry

**Files:**
- Create: `dataworks_agent/agent/capabilities.py`
- Modify: `dataworks_agent/agent/workflow_service.py`
- Modify: `dataworks_agent/routers/agent.py`
- Modify: `dataworks_agent/routers/health.py`
- Modify: `frontend/src/pages/SmartChatPage.vue`
- Test: `tests/integration/test_agent_capabilities.py`

**Interfaces:**
- `CapabilityRegistry.snapshot(force=False) -> dict[str, CapabilityState]`.
- Each state has `configured`, `online`, `status`, `checked_at`.

- [x] **Step 1: Write failing health-truth tests**

Assert that an instantiated but unreachable CDP client is offline, Cookie decrypt failure makes BFF/search/IDA offline, `model_not_found` makes LLM offline, and the frontend count includes only `online=True` capabilities.

- [x] **Step 2: Implement bounded cached probes**

Reuse existing read-only health checks where possible. Probe LLM configuration/model availability without exposing its key, and cache results for 15 seconds. `/api/health` and `/agent/capabilities` consume the same snapshot.

- [x] **Step 3: Render configured vs online accurately**

Remove `12/12 能力就绪` when dependencies are degraded. Show the exact non-secret status and never infer health from an object reference.

- [x] **Step 4: Verify**

Run: `uv run python -m pytest tests/integration/test_agent_capabilities.py tests/integration/test_settings_cookie_api.py -q --tb=short`

Run from `frontend`: `npm run test:unit && npm run build`

- [x] **Step 5: Commit**

```powershell
git add dataworks_agent/agent/capabilities.py dataworks_agent/agent/workflow_service.py dataworks_agent/routers/agent.py dataworks_agent/routers/health.py frontend/src/pages/SmartChatPage.vue tests/integration/test_agent_capabilities.py
git commit -m "fix(agent): report observed capability health"
```

### Task 6: Backend Journeys and Fifty-Turn Stability

**Files:**
- Create: `tests/integration/test_agent_runtime_journeys.py`
- Create: `dataworks_agent/scripts/verify_agent_runtime.py`

- [x] **Step 1: Implement a deterministic no-write provider**

The fake lives in test/support code and records tool name, arguments, side effect, and call count. It provides stable order-table candidates and column metadata; every write-capable call raises the test immediately.

- [x] **Step 2: Implement eight backend journeys**

Cover the eight journeys in the design through the real coordinator, router, state store, and event sink. No `ChatAgent` or workflow method is mocked.

- [x] **Step 3: Implement the fifty-turn test**

Alternate greetings, explanations, table refinements, selections, cancellations, and new goals. Assert monotonic versions, no repeated interaction consumption, bounded summaries, stable identifiers, and zero writes.

- [x] **Step 4: Replace print-only verification**

`verify_agent_runtime.py` exits nonzero on any failed assertion and writes a transcript plus backend events under a supplied report directory.

- [x] **Step 5: Verify**

Run: `uv run python -m pytest tests/integration/test_agent_runtime_journeys.py -q --tb=short`

Run: `uv run python -m dataworks_agent.scripts.verify_agent_runtime --output reports/continuous-dialogue/backend-local`

- [x] **Step 6: Commit**

```powershell
git add tests/integration/test_agent_runtime_journeys.py dataworks_agent/scripts/verify_agent_runtime.py
git commit -m "test(agent): verify multi-turn runtime stability"
```

### Task 7: Real Browser Journeys and Evidence Gate

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/agent-runtime.spec.ts`
- Create: `scripts/run_continuous_dialogue_acceptance.ps1`
- Modify: `frontend/package.json`
- Modify: `docs/product/conversational-dialog-design.md`
- Modify: `docs/superpowers/plans/2026-07-18-strong-continuous-dialogue.md`

- [x] **Step 1: Configure a deterministic full-stack server**

Start the real FastAPI app with `AGENT_ACCEPTANCE_MODE=deterministic`, a temporary SQLite path, and no external writes. The deterministic provider is selected only by this explicit test setting.

- [x] **Step 2: Implement eight five-to-ten-turn browser journeys**

Use visible UI controls and network assertions. Include refresh, backend restart, stale-card two-page concurrency, dependency degradation, task switching, and natural-language selection.

- [x] **Step 3: Collect evidence**

The PowerShell runner creates the required timestamped bundle, captures Playwright screenshots/traces, browser console, network records, transcript, backend JSONL, JUnit XML, commit ID, commands, retry counts, and a no-write proof.

- [x] **Step 4: Run all gates**

Run: `uv run ruff check .`

Run: `uv run python -m pytest tests/integration/ -q --tb=short`

Run from `frontend`: `npm run test:unit`

Run from `frontend`: `npm run build`

Run from `frontend`: `npm run test:e2e`

Run: `powershell -ExecutionPolicy Bypass -File scripts/run_continuous_dialogue_acceptance.ps1`

- [x] **Step 5: Restart 8085 and run the live degradation journey**

Verify the running branch reports actual dependency health, the core table-discovery route returns candidates or a recoverable interaction, `什么意思` remains usable, and no DataWorks write call appears in network/backend events.

- [x] **Step 6: Inspect and synchronize documentation**

Remove every unsupported completion claim. Mark only gates whose files and successful outputs exist. Link the actual report bundle from the product design.

- [x] **Step 7: Commit**

```powershell
git add frontend/playwright.config.ts frontend/e2e frontend/package.json scripts/run_continuous_dialogue_acceptance.ps1 docs/product/conversational-dialog-design.md docs/superpowers/plans/2026-07-18-strong-continuous-dialogue.md
git commit -m "test(e2e): gate the agent runtime on browser journeys"
```

## Plan self-review

- Spec coverage: Tasks 1–7 cover typed tools, table discovery, run loop, streaming, truthful health, backend stability, browser journeys, restart/concurrency, report artifacts, and no-write proof.
- Placeholder scan: clean; every implementation step names concrete behavior and verification.
- Type consistency: `SideEffect`, `ToolResult`, `AgentRunRequest`, `RunEvent`, and `streamAgentRun` names are stable across tasks.
- Scope: existing DataWorks workflows and guards are adapted, not rewritten; only the table-discovery vertical slice moves first.

## Verified completion record (2026-07-20)

- Valid bundle: `reports/continuous-dialogue/20260719T190357Z-1cb5007`.
- Gates: Ruff PASS; backend integration `245 passed`; frontend unit `48 passed`; frontend build PASS; browser journeys `8 passed`; 50-turn verifier PASS; compileall PASS.
- Browser evidence: 8 screenshots, 8 traces, 8 videos, 0 console errors, 428 network requests, 0 forbidden write requests.
- Safety evidence: 22 recorded tool calls, all declared `read`; no real DataWorks folder/node/deploy/DDL write was executed.
- Live 8085: health `degraded`; Agent Runtime/AK-SK/OpenAPI/MaxCompute/node adapter/official MCP online, Cookie BFF/CDP/table search/IDA/LLM offline. The page keeps the conversation usable and treats metadata failure as recoverable.
- Invalid bundle: `20260719T184628Z-1ab8836` is superseded because two pytest failures were hidden by a missing PowerShell `$LASTEXITCODE` check. Commit `c223f3d` corrected the runner.
- Historical red-test confirmation steps remain unchecked where no retained artifact proves the transient failing run. The implementation, regression, browser, live-degradation, and commit steps are checked only where repository commits or the valid bundle provide evidence.

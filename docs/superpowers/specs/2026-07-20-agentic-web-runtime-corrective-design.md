# Agentic Web Runtime Corrective Design

- Date: 2026-07-20
- Branch: `feat/strong-continuous-dialogue`
- Status: approved for implementation by the user after the 8085 dogfood failure review
- Scope: the Web Agent conversation runtime, table discovery vertical slice, event streaming, capability truthfulness, and real completion gates

## 1. Problem statement

The current page is a deterministic form workflow presented as an Agent. The primary browser journey fails as follows:

```text
你好
→ 查找数据表
→ generic ask_data SQL planning
→ configured LLM returns 503 model_not_found
→ read-only failure is marked execution_unknown
→ every later conversational turn is blocked
```

The system additionally reports Cookie, CDP, table search, and IDA as ready when only client objects exist. SSE sends one fixed status line and then waits for the complete response. The strong completion gate was marked complete without browser E2E files or the required report bundle.

## 2. Goal

Build the smallest genuine Agent runtime that makes the page behave like a tool-using conversational workspace rather than a card-driven form:

1. One conversation enters one run loop.
2. The loop can emit natural-language responses or invoke typed tools.
3. Table discovery is a first-class read-only tool, not SQL planning disguised as search.
4. Tool side effects determine failure policy; read-only failures never poison the conversation.
5. The page consumes one real event stream for normal text and structured interaction answers.
6. Capability status reflects observed health, including the configured LLM.
7. Completion requires real browser journeys and generated evidence.

The initial vertical slice covers greeting, free-form explanation, table discovery, candidate refinement, table selection, and safe read-only follow-ups. Existing modeling and node-write services remain available through guarded adapters; this change does not expand DataWorks write authority.

## 3. Approaches considered

### 3.1 Continue patching the deterministic state machine

Rejected. It minimizes code movement but grows more intent branches and continues coupling dialogue classification, workflow execution, persistence, and safety. The observed `ask_data → execution_unknown` failure is a direct consequence of this coupling.

### 3.2 Replace every workflow in one rewrite

Rejected. It would require reimplementing mature DataWorks logic, guards, directory confirmation, and Publish Gate behavior at the same time as the runtime change.

### 3.3 Strangler Agent runtime around existing services

Selected. Introduce a small run loop and typed tool registry. Migrate the browser conversation and table-discovery slice first. Existing services are invoked through adapters with explicit side-effect metadata. Later workflows can migrate without changing the UI protocol.

## 4. Architecture

```text
SmartChatPage
  POST /agent/runs/stream
    message | interaction_answer | conversation_id
        ↓
AgentRunCoordinator
  load ConversationGraph state
  resolve active interaction deterministically
  ask DecisionProvider for respond/tool/clarify
  execute typed tool through ToolRegistry
  observe result and continue (bounded loop)
  persist state and messages
        ↓
RunEventSink
  run.started
  turn.resolved
  tool.started
  tool.completed | tool.failed
  interaction.required
  response.completed
        ↓
NDJSON/SSE stream → page timeline/cards
```

Safety remains below the run loop:

```text
Agent decision
  → ToolRegistry lookup
  → typed input validation
  → side-effect policy
  → existing service/guard
  → typed observation
```

The model never calls DataWorks clients directly.

## 5. Components

### 5.1 AgentRunCoordinator

New module: `dataworks_agent/agent/run_coordinator.py`.

Responsibilities:

- own the bounded observe/decide/act loop;
- load and persist conversation state;
- resolve `interaction_answer` before model decisions;
- publish run events;
- choose failure recovery from tool side-effect metadata;
- stop after a configurable maximum of six decisions per turn;
- return one authoritative `ChatResponse` envelope.

It does not contain DataWorks business logic.

```python
class AgentRunCoordinator:
    async def run(
        self,
        request: AgentRunRequest,
        *,
        emit: Callable[[RunEvent], None],
    ) -> ChatResponse: ...
```

### 5.2 DecisionProvider

New module: `dataworks_agent/agent/decision_provider.py`.

The provider returns one of three validated decisions:

```python
RespondDecision(message: str, next_actions: list[...])
ToolDecision(tool_name: str, arguments: dict[str, Any])
ClarifyDecision(message: str, interaction: PendingInteraction)
```

Resolution order:

1. deterministic active-interaction answer;
2. deterministic safety and common dialogue actions;
3. deterministic selection of a tool for explicit known entries such as `find_table`;
4. LLM decision with a strict JSON schema when the model is healthy;
5. recoverable clarification when the LLM is unavailable or low-confidence.

An unavailable model is an observation, not an exception that locks the conversation.

### 5.3 ToolRegistry

New modules:

- `dataworks_agent/agent/tools/base.py`
- `dataworks_agent/agent/tools/registry.py`
- `dataworks_agent/agent/tools/table_discovery.py`
- `dataworks_agent/agent/tools/workflow_adapter.py`

Every tool declares:

```python
class SideEffect(str, Enum):
    NONE = "none"
    READ = "read"
    DEV_WRITE = "dev_write"
    DESTRUCTIVE = "destructive"
    PUBLISH = "publish"

class AgentTool(Protocol):
    name: str
    side_effect: SideEffect
    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...
```

Only `DEV_WRITE`, `DESTRUCTIVE`, and `PUBLISH` can enter uncertain-execution recovery, and only after the adapter reports that the write boundary was crossed. `NONE` and `READ` failures return a retry/clarification observation and keep the conversation active.

### 5.4 TableDiscoveryTool

`find_table` becomes an explicit tool. It calls existing metadata discovery capabilities but never falls through to SQL generation.

Inputs:

```json
{
  "keyword": "订单",
  "layer": "dwd",
  "project": "optional",
  "limit": 8
}
```

Outputs:

- 1–8 candidates: `select_table` interaction;
- more than 8 candidates: `select_layer` or refinement interaction;
- no candidates: recoverable free-text clarification with truthful source-health details;
- dependency unavailable: recoverable tool failure with retry and capability actions.

It preserves full `project.table` values in server-owned option payloads.

### 5.5 Run events and streaming API

New request endpoint:

```text
POST /agent/runs/stream
Content-Type: application/json
Response: application/x-ndjson
```

The request uses the existing `ChatRequest` fields, including `interaction_answer`. The response emits validated `RunEvent` objects followed by exactly one `response.completed` event containing the authoritative response.

Required event types:

```text
run.started
context.loaded
turn.resolved
decision.made
tool.started
tool.completed | tool.failed
interaction.required
state.persisted
response.completed
```

The legacy GET SSE and POST chat endpoints remain compatible but delegate to the same coordinator. They are no longer separate behavioral implementations.

### 5.6 Frontend run client

`frontend/src/components/agent/runStream.ts` becomes the only page transport for both typed messages and interaction answers.

`SmartChatPage.vue`:

- renders progress from real run events;
- shows the active tool and truthful wait reason;
- replaces the temporary assistant message only on `response.completed`;
- unlocks retry on a recoverable tool failure;
- never labels an HTTP connection as a healthy real-time Agent capability;
- uses the server conversation envelope as the authority.

The old `createSSEStream()` remains only as a compatibility wrapper or is removed after all callers migrate.

### 5.7 CapabilityRegistry

New module: `dataworks_agent/agent/capabilities.py`.

Capability state separates configuration, client construction, and observed health:

```json
{
  "llm": {"configured": true, "online": false, "status": "model_not_found"},
  "cookie_bff": {"configured": true, "online": false, "status": "cookie_decrypt_failed"},
  "cdp_9222": {"configured": true, "online": false, "status": "unreachable"}
}
```

Probes are read-only, bounded by short timeouts, cached briefly, and never expose secrets. The page count is derived from `online`, not object presence. `/api/health` and `/agent/capabilities` use the same registry snapshot.

## 6. Conversation and failure semantics

### 6.1 Read-only failure

```text
tool.failed(side_effect=READ)
→ keep active_goal and selected_resources
→ task_status=waiting_user or degraded
→ return retry/change-source/custom-input interaction
→ ordinary greeting/explain/new-goal remains available
```

### 6.2 Uncertain write

```text
tool adapter reports write_boundary_crossed=true
and result cannot be confirmed
→ task_status=execution_unknown
→ block duplicate write only
→ still allow explanation, health checks, and a new unrelated goal
```

The previous global block on every conversation action is removed.

### 6.3 Model failure

```text
LLM unavailable before a tool call
→ deterministic tool route if possible
→ otherwise clarification

LLM unavailable after a read tool observation
→ summarize with deterministic response policy
→ preserve result and allow follow-up
```

No model error is presented as a DataWorks write uncertainty.

## 7. Testing and completion gate

### 7.1 Deterministic backend journeys

Use a no-write fake tool provider, not mocked `ChatAgent` methods. Exercise the real coordinator, state store, router, event stream, and response policy.

Required journeys:

1. greeting → find table → explain → select second → view columns;
2. find table → DWD refinement → custom refinement → select table;
3. read tool unavailable → retry interaction → new goal remains usable;
4. LLM unavailable → deterministic find table still works;
5. refresh restore;
6. new coordinator instance restart restore;
7. stale interaction rejection across two clients;
8. task switch without parameter pollution.

The 50-turn test asserts monotonic state version, bounded summary/context, no duplicate tool execution, and no cross-goal contamination.

### 7.2 Browser E2E

Add Playwright configuration and eight page journeys against a deterministic full-stack server. Capture console, network, screenshots, transcript, backend events, and JUnit results.

Add one live-environment degradation journey against port 8085:

- capabilities reflect real unavailable dependencies;
- a read-only failure produces a recoverable response;
- ordinary explanation and new-goal input remain usable;
- no DataWorks write endpoint is called.

### 7.3 Evidence bundle

Every completion run creates:

```text
reports/continuous-dialogue/<run-id>/
  summary.md
  conversation-transcript.json
  backend-events.jsonl
  frontend-console.json
  network-events.json
  test-results.xml
  screenshots/
  failures/
```

No checkbox may be marked complete unless its named artifact exists and its command exits successfully.

## 8. DataWorks safety constraints

- Never create a DataWorks folder or business-process directory.
- Automated tests use deterministic providers, mocks at external-client boundaries, or read-only probes.
- No real DataWorks node write is performed without explicit user authorization.
- Existing parent-directory confirmation, exact path/name reuse, destructive guard, and Publish Gate remain authoritative.
- The Agent model cannot bypass a tool adapter or call OpenAPI/BFF clients directly.

## 9. Migration sequence

1. Add tool contracts and side-effect failure policy.
2. Implement first-class table discovery.
3. Add run coordinator and decision provider.
4. Make legacy chat APIs delegate to the coordinator.
5. Add real run stream and migrate the page.
6. Add truthful capability registry.
7. Add backend journeys, 50-turn test, browser journeys, and report generator.
8. Remove the false completion claims and publish evidence only after the full gate passes.

## 10. Completion definition

The task is complete only when all of the following are true:

- the real browser journey `你好 → 查找数据表 → 解释 → 选择 → 查看字段` completes or returns a recoverable dependency interaction;
- a broken LLM model does not prevent deterministic table discovery;
- a read-only failure never produces `execution_unknown`;
- ordinary dialogue remains usable after every read-only failure;
- the page displays real run events and truthful capability health;
- backend integration, frontend unit tests, build, Ruff, eight browser journeys, and the 50-turn test pass;
- refresh, restart, and stale-card recovery pass;
- a complete evidence bundle is generated and manually inspected;
- no unauthorized DataWorks write or directory creation occurs.


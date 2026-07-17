# Structured Continuous Dialogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recoverable structured option/custom-answer conversations to the existing Agent, beginning with table discovery, while enforcing test and production node-placement rules without creating DataWorks directories.

**Architecture:** Introduce a small interaction protocol and reducer, persist the active interaction in the existing LangGraph checkpoint, and adapt existing `option_chips`/`next_actions` into that protocol. Keep `/agent/chat`, `conversation_id`, `AgentWorkflowService`, and existing business executors; frontend messages render immutable interaction snapshots while only the checkpoint-designated active interaction remains actionable. Node placement is isolated behind an environment-aware policy that only returns already-confirmed directories.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, LangGraph SQLite checkpointer, Vue 3, TypeScript, Vitest, pytest, DataWorks OpenAPI 2024-05-18, Cookie/DataStudio read-only fallback.

## Global Constraints

- Never create a DataWorks folder, business process, or warehouse-layer directory in production.
- Test node writes may only target already-existing directories under `业务流程/106_广告报告/MaxCompute/数据开发`.
- Before create/update, read-only confirm the exact parent directory and query the exact full node path.
- Reuse an existing node UUID when the same path/name exists; do not create duplicates.
- OpenAPI node creation uses `container_id=None`, `scene="DATAWORKS_PROJECT"`, and FlowSpec `script.path` for placement.
- Production publication remains behind Publish Gate.
- Preserve full `project.table` identifiers end to end.
- Existing text-only `/agent/chat` callers remain compatible.
- Use only declared project commands; backend verification uses `uv run python -m pytest tests/integration/ -q --tb=short` and `uv run ruff check .`; frontend verification uses `npm run test:unit` and `npm run build` from `frontend`.

---

## File Structure

**Create**

- `dataworks_agent/agent/interaction.py`: interaction/answer schemas, option adaptation, validation, reducer helpers.
- `dataworks_agent/modeling/node_placement.py`: environment-aware directory candidate and confirmation policy; contains no node-write implementation.
- `tests/integration/test_agent_interaction.py`: backend interaction state/API/recovery coverage.
- `tests/integration/test_node_placement_policy.py`: test/production directory policy coverage.

**Modify**

- `dataworks_agent/agent/conversation_graph.py`: persist active interaction, selected resources, last result, and state version.
- `dataworks_agent/agent/core.py`: resolve structured answers before NLU, persist structured assistant payloads, and clear/advance interactions.
- `dataworks_agent/agent/workflow_service.py`: expose existing table candidates/next actions through the interaction adapter and accept confirmed table params.
- `dataworks_agent/routers/agent.py`: request schema for `interaction_answer`; restore active interaction through `/messages`; WebSocket parity.
- `dataworks_agent/db/models.py`: structured message payload column.
- `dataworks_agent/api_clients/openapi_node_adapter.py`: inject/require directory evidence and preserve exact reuse behavior.
- `frontend/src/components/agent/chatInteraction.ts`: shared TS interaction types and structured request builder.
- `frontend/src/components/agent/MessageBubble.vue`: render current/answered/expired interactions and custom input.
- `frontend/src/pages/SmartChatPage.vue`: send answers and restore active interaction.
- `frontend/src/components/agent/AgentChat.vue`: keep alternate chat entry compatible.
- `frontend/src/__tests__/agentChatInteraction.spec.ts`: request-shape tests.
- `docs/product/conversational-dialog-design.md`: mark the implemented slice and environment-specific placement policy.

---

### Task 1: Interaction Protocol and Adapter

**Files:**
- Create: `dataworks_agent/agent/interaction.py`
- Test: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Produces: `InteractionOption`, `PendingInteraction`, `InteractionAnswer` Pydantic models.
- Produces: `build_interaction(data: dict[str, Any], *, purpose: str, state_version: int) -> PendingInteraction | None`.
- Produces: `resolve_interaction_answer(pending: PendingInteraction, answer: InteractionAnswer) -> dict[str, Any]`.
- Consumes existing `option_chips`, `next_actions`, `clarifying_questions`, `allow_custom_input`, and `custom_input_hint` shapes.

- [ ] **Step 1: Write failing protocol tests**

```python
from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    build_interaction,
    resolve_interaction_answer,
)


def test_build_interaction_from_table_option_chips():
    pending = build_interaction(
        {
            "option_chips": [
                {
                    "type": "pick_table",
                    "id": "opt_0",
                    "label": "giikin_aliyun.tb_dwd_order",
                    "value": "giikin_aliyun.tb_dwd_order",
                    "layer": "dwd",
                },
                {"type": "free_text", "id": "opt_custom", "label": "输入其它"},
            ],
            "clarifying_questions": ["请选择目标表"],
        },
        purpose="select_table",
        state_version=1,
    )
    assert pending is not None
    assert pending.allow_custom_input is True
    assert pending.options[0].value == "giikin_aliyun.tb_dwd_order"


def test_resolve_answer_uses_server_option_value():
    pending = build_interaction(
        {"next_actions": [{"id": "dwd", "label": "DWD", "payload": {"params": {"layer": "dwd"}}}]},
        purpose="select_layer",
        state_version=2,
    )
    result = resolve_interaction_answer(
        pending,
        InteractionAnswer(interaction_id=pending.interaction_id, option_id="dwd", state_version=2),
    )
    assert result == {"params": {"layer": "dwd"}}
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short`

Expected: FAIL because `dataworks_agent.agent.interaction` does not exist.

- [ ] **Step 3: Implement minimal schemas and adapter**

```python
class InteractionOption(BaseModel):
    id: str
    label: str
    value: Any = None
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class PendingInteraction(BaseModel):
    interaction_id: str
    type: Literal["single_select", "confirm", "free_text"]
    purpose: str
    prompt: str
    options: list[InteractionOption] = Field(default_factory=list)
    allow_custom_input: bool = True
    custom_input_placeholder: str = ""
    status: Literal["pending", "answered", "expired", "cancelled"] = "pending"
    state_version: int
```

`resolve_interaction_answer` must reject mismatched IDs/versions with a dedicated `InteractionExpiredError` and return only payload/value loaded from the server-side pending object.

- [ ] **Step 4: Run focused tests**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add dataworks_agent/agent/interaction.py tests/integration/test_agent_interaction.py
git commit -m "feat(agent): add structured interaction protocol"
```

---

### Task 2: Persist Interaction State in ConversationGraph

**Files:**
- Modify: `dataworks_agent/agent/conversation_graph.py`
- Test: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Produces: `ConversationGraph.context()` keys `selected_resources`, `pending_interaction`, `last_result`, `state_version`.
- Produces: `ConversationGraph.remember(..., pending_interaction=None, selected_resources=None, last_result=None)`.
- Produces: `ConversationGraph.answer(conversation_id, answer) -> dict[str, Any]`.
- Consumes Task 1 `InteractionAnswer` and `resolve_interaction_answer`.

- [ ] **Step 1: Add failing persistence/restart tests**

```python
@pytest.mark.asyncio
async def test_pending_interaction_survives_new_graph_instance(tmp_path):
    db = tmp_path / "conversation.db"
    first = ConversationGraph(str(db))
    pending = build_interaction(
        {"next_actions": [{"id": "dwd", "label": "DWD", "value": "dwd"}]},
        purpose="select_layer",
        state_version=1,
    )
    await first.remember("conv-1", "找订单表", needs_clarification=True, pending_interaction=pending.model_dump())

    second = ConversationGraph(str(db))
    state = await second.context("conv-1")
    assert state["pending_interaction"]["interaction_id"] == pending.interaction_id
```

Also test cancellation clears pending state and answering increments `state_version`.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because the graph does not store the new fields.

- [ ] **Step 3: Extend state and fix async initialization**

Add fields to `ConversationState`, await `_ensure_initialized()` in every async method, and protect initialization with an `asyncio.Lock` so concurrent first requests do not compile multiple graphs.

- [ ] **Step 4: Implement answer reducer**

`answer()` loads the current pending interaction, calls Task 1 validation, marks the interaction answered, increments the version, and returns the resolved payload/custom text without invoking business services.

- [ ] **Step 5: Run focused tests**

Expected: PASS including restart recovery.

- [ ] **Step 6: Commit**

```powershell
git add dataworks_agent/agent/conversation_graph.py tests/integration/test_agent_interaction.py
git commit -m "feat(agent): persist pending conversation interactions"
```

---

### Task 3: API and Core Structured-Answer Flow

**Files:**
- Modify: `dataworks_agent/routers/agent.py`
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/db/models.py`
- Test: `tests/integration/test_agent_api.py`
- Test: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Consumes: Task 1 `InteractionAnswer`.
- Produces: `ChatRequest.interaction_answer: InteractionAnswer | None`.
- Produces: `GET /agent/messages` response keys `messages`, `active_interaction`, `state_version`.
- Produces: history rows with `payload_json` while keeping readable `content`.

- [ ] **Step 1: Add failing API compatibility tests**

Test that text-only requests are unchanged, structured answers are forwarded to `ChatAgent.chat`, WebSocket requests accept the same field, and `/messages` includes active interaction.

- [ ] **Step 2: Run focused API tests**

Run: `uv run python -m pytest tests/integration/test_agent_api.py tests/integration/test_agent_interaction.py -q --tb=short`

Expected: FAIL on missing request/response fields.

- [ ] **Step 3: Extend request and history models**

Add `interaction_answer` to the router model and `payload_json: Text` to `ConversationHistoryModel`. Rely on the existing SQLite additive-column migration path; old rows default to `{}`.

- [ ] **Step 4: Resolve answers before NLU**

In `ChatAgent.chat`:

```python
if interaction_answer is not None:
    resolved = await self._conversation_graph.answer(conversation_id, interaction_answer)
    context_updates = self._merge_context_updates(context_updates, resolved)
```

For a selected table option, write the exact full value into `params["table_name"]` and `selected_resources["table"]`. For custom text, preserve the root objective and send the custom text through the current workflow as supplemental input.

- [ ] **Step 5: Persist readable and structured assistant history**

Save `content=response.message`; save interaction/artifact snapshot separately in `payload_json`. Update history loading to parse JSON defensively.

- [ ] **Step 6: Return `interaction_expired` safely**

Catch `InteractionExpiredError` and return a normal ChatResponse with `success=False`, `error="interaction_expired"`, plus the current active interaction.

- [ ] **Step 7: Run focused tests**

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add dataworks_agent/routers/agent.py dataworks_agent/agent/core.py dataworks_agent/db/models.py tests/integration/test_agent_api.py tests/integration/test_agent_interaction.py
git commit -m "feat(agent): process and restore interaction answers"
```

---

### Task 4: Adapt Table Discovery and Follow-Up Actions

**Files:**
- Modify: `dataworks_agent/agent/workflow_service.py`
- Modify: `dataworks_agent/agent/core.py`
- Test: `tests/integration/test_agent_interaction.py`
- Test: `tests/integration/test_agent_integration.py`

**Interfaces:**
- Consumes: Task 1 `build_interaction`.
- Produces: `data.interaction` for clarification results.
- Produces: post-selection actions `view_columns`, `preview_data`, `view_partitions`, `view_lineage`, `generate_ods_node`, `generate_dwd_node`.

- [ ] **Step 1: Add failing three-turn table-flow tests**

Mock metadata discovery so:

```text
找订单表 → table interaction
选择 opt_0 → selected_resources.table is full project.table
查字段 → existing read-only path receives the same full table
```

Add a custom-answer case (`只要 dwd`) and a stale-option case.

- [ ] **Step 2: Run focused flow tests**

Expected: FAIL because clarification data has only `option_chips`.

- [ ] **Step 3: Adapt clarification results**

Keep `option_chips` for compatibility, but add a normalized `interaction`. Use table-layer grouping when candidate count exceeds eight; otherwise return up to eight table options.

- [ ] **Step 4: Add selected-table action interaction**

After an exact table selection, return a `select_action` interaction. Read-only action payloads contain the exact selected table. Node-generation actions only prepare a plan/confirmation; they do not write yet.

- [ ] **Step 5: Preserve custom answers and identifiers**

Custom text refines the prior objective. Ensure `project.table` is not stripped by entity extraction or param merging.

- [ ] **Step 6: Run flow tests**

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add dataworks_agent/agent/workflow_service.py dataworks_agent/agent/core.py tests/integration/test_agent_interaction.py tests/integration/test_agent_integration.py
git commit -m "feat(agent): add continuous table-selection flow"
```

---

### Task 5: Frontend Structured Interaction UI

**Files:**
- Modify: `frontend/src/components/agent/chatInteraction.ts`
- Modify: `frontend/src/components/agent/MessageBubble.vue`
- Modify: `frontend/src/pages/SmartChatPage.vue`
- Modify: `frontend/src/components/agent/AgentChat.vue`
- Modify: `frontend/src/__tests__/agentChatInteraction.spec.ts`
- Test: `frontend/src/__tests__/agentStructuredInteraction.spec.ts`

**Interfaces:**
- Consumes backend `interaction` and `active_interaction` shapes from Tasks 1-4.
- Produces: `InteractionAnswer`, `AgentInteraction`, request builder `interactionAnswer?` parameter.
- Emits: `answer-interaction` with `{ message, answer }` from `MessageBubble`.

- [ ] **Step 1: Add failing TypeScript request tests**

```ts
expect(buildAgentChatRequest(
  'DWD', 'auto', true, false, 'conv-1', undefined,
  { interaction_id: 'int-1', option_id: 'dwd', state_version: 2 },
)).toMatchObject({
  conversation_id: 'conv-1',
  interaction_answer: { interaction_id: 'int-1', option_id: 'dwd', state_version: 2 },
})
```

- [ ] **Step 2: Add failing component tests**

Verify options render, custom input always appears when allowed, one click emits once and locks, request failure unlocks, answered/expired cards remain visible but disabled, and restored active interaction is actionable.

- [ ] **Step 3: Implement shared TS types/request builder**

Add exact backend-compatible snake_case fields; preserve existing `context_updates` calls.

- [ ] **Step 4: Upgrade MessageBubble**

Render `interaction.options`; maintain local custom input; emit structured answer; disable unless status is `pending` and message is the active interaction.

- [ ] **Step 5: Wire SmartChatPage restore/send**

Load structured message payloads from `/agent/messages`, identify `active_interaction`, and attach it to the matching assistant message. On answer, add a readable user message and send the structured payload.

- [ ] **Step 6: Keep AgentChat compatible**

Extend its payload types and sender without redesigning its layout.

- [ ] **Step 7: Run frontend tests/build**

Run:

```powershell
Set-Location frontend
npm run test:unit
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/components/agent/chatInteraction.ts frontend/src/components/agent/MessageBubble.vue frontend/src/pages/SmartChatPage.vue frontend/src/components/agent/AgentChat.vue frontend/src/__tests__
git commit -m "feat(frontend): render recoverable agent interactions"
```

---

### Task 6: Environment-Aware Node Placement Policy

**Files:**
- Create: `dataworks_agent/modeling/node_placement.py`
- Modify: `dataworks_agent/api_clients/openapi_node_adapter.py`
- Test: `tests/integration/test_node_placement_policy.py`

**Interfaces:**
- Produces: `NodePlacementRequest(environment, layer, business_domain, requested_path)`.
- Produces: `NodePlacementDecision(status, candidates, selected_path, evidence, reason)`.
- Produces: `NodePlacementPolicy.resolve(request, directory_reader) -> NodePlacementDecision`.
- Consumes a read-only `directory_reader(path) -> ExistingDirectoryEvidence` callback.

- [ ] **Step 1: Add failing placement tests**

Cover:

- test DWD resolves only to `业务流程/106_广告报告/MaxCompute/数据开发/02_DWD` after positive evidence;
- test DIM blocks because `01_DIM` is not confirmed;
- production unique candidate resolves;
- production multiple candidates returns `needs_context` with options;
- production missing evidence blocks;
- no decision ever requests directory creation.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because the policy module is absent.

- [ ] **Step 3: Implement policy**

Use the fixed test mapping from the spec. Production accepts candidates supplied by the existing semantic/config layer, then retains only paths with positive online evidence. It must not synthesize missing paths.

- [ ] **Step 4: Harden OpenAPINodeAdapter evidence injection**

Allow `create_node(..., directory_evidence=...)`; if evidence is absent, stale, false, or for a different parent path, stop before `create_node`. Keep exact path reuse first.

- [ ] **Step 5: Run focused tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add dataworks_agent/modeling/node_placement.py dataworks_agent/api_clients/openapi_node_adapter.py tests/integration/test_node_placement_policy.py
git commit -m "feat(modeling): enforce safe node placement policy"
```

---

### Task 7: Node Confirmation Interaction and Existing Write Path Integration

**Files:**
- Modify: `dataworks_agent/agent/workflow_service.py`
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/services/ods_oss/pipeline.py`
- Modify: `dataworks_agent/agent/workflow_service.py:3100-3880` (standard OSS/ODS/DWD execution path)
- Test: `tests/integration/test_agent_interaction.py`
- Test: `tests/integration/test_modeling_api.py`

**Interfaces:**
- Consumes Task 6 `NodePlacementPolicy` and `NodePlacementDecision`.
- Produces a `confirm_node_write` interaction containing node name, exact parent path, full node path, create/update mode, and publish boundary.
- Confirm payload contains server-owned placement decision ID or complete server checkpoint data; it never trusts a client-supplied path.

- [ ] **Step 1: Add failing confirmation tests**

Test that generate-node action returns confirmation without writing, confirmation rechecks directory evidence and exact node path, existing UUID updates, missing node creates draft only, and production ambiguous/missing directories block.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because node-generation actions are plan-only.

- [ ] **Step 3: Build confirmation interaction**

The first action resolves placement and exact-node lookup, stores the decision in checkpoint, and returns confirm/cancel/modify-name options.

- [ ] **Step 4: Execute only confirmed writes**

On confirm, re-run directory evidence and exact lookup, call existing OpenAPI adapter, then read back `GetNode` and validate path/name/language/script. Do not publish.

- [ ] **Step 5: Run focused tests**

Expected: PASS with mocked clients and zero folder-create calls.

- [ ] **Step 6: Optional real test-node verification**

Only if credentials and current directory evidence are available, create a uniquely named test node under the confirmed advertisement-report layer, read it back, and remove only that exact test node after verification. Never create directories or publish.

- [ ] **Step 7: Commit**

```powershell
git add dataworks_agent/agent/workflow_service.py dataworks_agent/agent/core.py dataworks_agent/modeling tests/integration
git commit -m "feat(agent): confirm safe DataWorks node writes"
```

---

### Task 8: Regression, Documentation, and Final Verification

**Files:**
- Modify: `docs/product/conversational-dialog-design.md`
- Modify: `docs/superpowers/specs/2026-07-17-structured-continuous-dialogue-design.md` only if implementation discovers a factual mismatch.

**Interfaces:**
- Consumes all previous tasks.
- Produces validated end-to-end behavior and implementation status documentation.

- [ ] **Step 1: Run backend integration suite**

Run: `uv run python -m pytest tests/integration/ -q --tb=short`

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check .`

Expected: no violations.

- [ ] **Step 3: Run frontend tests and build**

```powershell
Set-Location frontend
npm run test:unit
npm run build
```

Expected: all tests and TypeScript/Vite build pass.

- [ ] **Step 4: Verify no directory-create behavior**

Search production sources for Folder/create-directory behavior in the changed path and confirm node placement only calls Node creation after positive directory evidence.

- [ ] **Step 5: Update implementation-status documentation**

Document the completed slice, remaining non-goals, exact test/production placement behavior, and whether a real test node was exercised.

- [ ] **Step 6: Commit final verification/docs**

```powershell
git add docs dataworks_agent frontend tests
git commit -m "docs: record continuous dialogue implementation"
```




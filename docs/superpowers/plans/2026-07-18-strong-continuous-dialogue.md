# Strong Continuous Dialogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reliable multi-turn dialogue that understands contextual short replies, renders mixed-strategy action cards, survives page/backend restarts, rejects stale interactions, and produces complete correlated test logs.

**Architecture:** Add a deterministic-first `ContextResolver` before the existing NLU, keep one versioned `PendingInteraction` in the LangGraph-backed conversation state, and centralize card creation in a `ResponsePolicy`. Reuse the existing EventLog as the queryable trace source while also emitting a rotating JSONL conversation log; keep existing DataWorks workflows and safety guards unchanged.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2, LangGraph 1.2.9–1.x, SQLite/SQLAlchemy, Vue 3, TypeScript, Vite, Vitest, Playwright, pytest, Ruff.

## Global Constraints

- Never create a DataWorks folder or directory through any API, test, helper, or fallback path.
- Automated tests use mocks, read-only probes, or existing data; they do not create, update, delete, deploy, or publish real DataWorks nodes without explicit authorization.
- Preserve the long-term AK/SK and Cookie/BFF capability split in `AGENTS.md`.
- Preserve complete resource identifiers such as `project.table`; do not send a selected identifier back through fuzzy NLU extraction.
- Keep at most one `pending` interaction per conversation and reject stale `interaction_id` or `state_version` values.
- Greeting, explanation, context summary, and history restoration are read-only.
- Mask AK/SK, Cookie, Authorization, personal data, and sensitive SQL before log persistence.
- Use project-declared commands: `uv run python -m pytest tests/integration/ -q --tb=short`, `uv run ruff check .`, `npm run test:unit`, `npm run build`, and `npm run test:e2e`.
- Do not report completion until Task 10 passes and `reports/continuous-dialogue/<run-id>/` contains the required evidence.

## File Map

**Create**

- `dataworks_agent/agent/context_resolver.py` — contextual turn classification and rewriting.
- `dataworks_agent/agent/response_policy.py` — greeting, clarification, explanation, and card policy.
- `dataworks_agent/agent/conversation_events.py` — correlated EventLog and JSONL dialogue events.
- `tests/integration/test_context_resolver.py`
- `tests/integration/test_conversation_events.py`
- `tests/integration/test_continuous_dialogue_journeys.py`
- `tests/e2e/dialogue_server.py`
- `frontend/src/__tests__/conversationLifecycle.spec.ts`
- `frontend/playwright.config.ts`
- `frontend/e2e/continuous-dialogue.spec.ts`

**Modify**

- `dataworks_agent/agent/conversation_graph.py`
- `dataworks_agent/agent/interaction.py`
- `dataworks_agent/agent/core.py`
- `dataworks_agent/routers/agent.py`
- `dataworks_agent/eventlog/store.py`
- `dataworks_agent/main.py`
- `dataworks_agent/routers/logs.py`
- `dataworks_agent/scripts/test_continuous_dialogue.py`
- `tests/integration/test_agent_interaction.py`
- `tests/integration/test_agent_api.py`
- `frontend/src/components/agent/chatInteraction.ts`
- `frontend/src/components/agent/MessageBubble.vue`
- `frontend/src/pages/SmartChatPage.vue`
- existing frontend interaction specs, `README.md`, and `docs/product/conversational-dialog-design.md`

---

### Task 1: Deterministic-First Context Resolver

**Files:**
- Create: `dataworks_agent/agent/context_resolver.py`
- Create: `tests/integration/test_context_resolver.py`

**Interfaces:**
- Consumes: `InteractionAnswer` and the dictionary returned by `ConversationGraph.context()`.
- Produces: `DialogueAction`, `ResolvedTurn`, `SemanticTurnFallback`, and `ContextResolver.resolve(message, context)`.

- [ ] **Step 1: Write failing classification tests**

```python
from __future__ import annotations

import pytest

from dataworks_agent.agent.context_resolver import ContextResolver, DialogueAction, ResolvedTurn


def _context(with_interaction: bool = True) -> dict:
    interaction = {
        "interaction_id": "int_orders",
        "type": "single_select",
        "purpose": "select_table",
        "prompt": "请选择候选表",
        "options": [
            {"id": "detail", "label": "订单明细表", "value": "dw.dwd_order_detail", "payload": {"selected_resources": {"table": "dw.dwd_order_detail"}}},
            {"id": "summary", "label": "订单汇总表", "value": "dw.dws_order_summary", "payload": {"selected_resources": {"table": "dw.dws_order_summary"}}},
        ],
        "allow_custom_input": True,
        "custom_input_placeholder": "输入其他条件",
        "state_version": 4,
        "status": "pending",
    }
    return {
        "objective": "查找订单相关表",
        "action": "ask_data",
        "params": {"layer": "dwd"},
        "selected_resources": {},
        "pending_interaction": interaction if with_interaction else {},
        "last_assistant_turn": {"content": "我找到了订单明细表和订单汇总表。"},
        "state_version": 4,
    }


@pytest.mark.parametrize(("message", "action"), [
    ("什么意思", DialogueAction.EXPLAIN),
    ("继续", DialogueAction.CONTINUE),
    ("你好", DialogueAction.GREETING),
    ("取消这个任务", DialogueAction.CANCEL),
    ("换成 DWS", DialogueAction.MODIFY),
])
async def test_classifies_contextual_short_turns(message, action):
    assert (await ContextResolver().resolve(message, _context())).dialogue_action is action


async def test_maps_ordinal_to_server_option():
    result = await ContextResolver().resolve("第二个", _context())
    assert result.dialogue_action is DialogueAction.ANSWER
    assert result.interaction_answer.option_id == "summary"
    assert result.interaction_answer.state_version == 4


async def test_preserves_full_selected_identifier():
    context = _context(False)
    context["selected_resources"] = {"table": "dw.dws_order_summary"}
    result = await ContextResolver().resolve("用刚才那张表继续", context)
    assert result.context_updates == {"selected_resources": {"table": "dw.dws_order_summary"}}
    assert "dw.dws_order_summary" in result.rewritten_message
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `uv run python -m pytest tests/integration/test_context_resolver.py -q --tb=short`

Expected: collection fails with `ModuleNotFoundError: dataworks_agent.agent.context_resolver`.

- [ ] **Step 3: Implement the resolver contracts**

```python
from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from dataworks_agent.agent.interaction import InteractionAnswer, PendingInteraction


class DialogueAction(StrEnum):
    NEW_GOAL = "new_goal"
    ANSWER = "answer"
    CONTINUE = "continue"
    EXPLAIN = "explain"
    MODIFY = "modify"
    REFER = "refer"
    CANCEL = "cancel"
    GREETING = "greeting"
    RESET = "reset"
    CLARIFY = "clarify"


class ResolvedTurn(BaseModel):
    dialogue_action: DialogueAction
    rewritten_message: str
    context_updates: dict[str, Any] = Field(default_factory=dict)
    resolved_references: list[str] = Field(default_factory=list)
    interaction_answer: InteractionAnswer | None = None
    resolver: str = "deterministic"
    confidence: float = 1.0
    consume_interaction: bool = False


class SemanticTurnFallback(Protocol):
    async def classify(self, message: str, context: dict[str, Any]) -> ResolvedTurn | None:
        raise NotImplementedError


class LLMDialogueFallback:
    def __init__(self, classifier: Any | None = None) -> None:
        self._classifier = classifier

    async def classify(self, message: str, context: dict[str, Any]) -> ResolvedTurn | None:
        if self._classifier is None:
            try:
                from dataworks_agent.agent.llm_intent_classifier import LLMIntentClassifier
                self._classifier = LLMIntentClassifier()
            except Exception:
                return None
        compact = {
            "objective": context.get("objective"),
            "action": context.get("action"),
            "selected_resources": context.get("selected_resources"),
        }
        result = await self._classifier.classify(
            f"当前会话上下文：{json.dumps(compact, ensure_ascii=False)}\n用户输入：{message}"
        )
        mapping = {
            "greeting": DialogueAction.GREETING,
            "clarification": DialogueAction.CLARIFY,
            "ask_data": DialogueAction.NEW_GOAL,
            "modeling": DialogueAction.NEW_GOAL,
            "diagnosis": DialogueAction.NEW_GOAL,
        }
        action = mapping.get(result.action)
        if action is None:
            return None
        return ResolvedTurn(
            dialogue_action=action,
            rewritten_message=message,
            context_updates={"params": result.params},
            resolver="llm",
            confidence=float(result.confidence),
        )
```

Implement `ContextResolver.resolve()` in this exact order:

1. explicit reset;
2. cancel;
3. greeting;
4. explanation;
5. continue;
6. pending interaction ordinal/label answer;
7. layer/execution-mode/date modification;
8. selected-resource reference;
9. deterministic `NEW_GOAL` when the text contains a known DataWorks task verb or entity;
10. injected semantic fallback for remaining ambiguous substantive text when confidence is at least `0.7`;
11. `CLARIFY` for unresolved short or low-confidence text.

Ordinal mapping must include `第一个/第1个`, `第二个/第2个`, `第三个/第3个`, and `最后一个`. Label matching must compare both `InteractionOption.label` and `InteractionOption.value` without changing the stored payload.

- [ ] **Step 4: Add fallback and missing-card tests**

```python
class FakeFallback:
    async def classify(self, message, context):
        return ResolvedTurn(
            dialogue_action=DialogueAction.MODIFY,
            rewritten_message=context["objective"] + "\n补充信息：最近七天",
            context_updates={"params": {"date_range": "last_7_days"}},
            resolver="llm",
            confidence=0.91,
        )


async def test_uses_high_confidence_semantic_fallback():
    result = await ContextResolver(FakeFallback()).resolve("再加上最近七天", _context(False))
    assert result.resolver == "llm"
    assert result.context_updates["params"]["date_range"] == "last_7_days"


async def test_ordinal_without_card_requires_clarification():
    result = await ContextResolver().resolve("第二个", _context(False))
    assert result.dialogue_action is DialogueAction.CLARIFY
    assert result.interaction_answer is None
```

- [ ] **Step 5: Run resolver tests**

Run: `uv run python -m pytest tests/integration/test_context_resolver.py -q --tb=short`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add dataworks_agent/agent/context_resolver.py tests/integration/test_context_resolver.py
git commit -m "feat(dialogue): add contextual turn resolver"
```

---

### Task 2: Versioned Recoverable Conversation State

**Files:**
- Modify: `dataworks_agent/agent/conversation_graph.py:20-223`
- Modify: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Produces: richer `context()`, version-aware `remember()`, atomic `answer()`, `cancel()`, and `ConversationStateConflictError`.

- [ ] **Step 1: Add failing persistence and conflict tests**

```python
from dataworks_agent.agent.conversation_graph import ConversationGraph, ConversationStateConflictError


async def test_rich_context_survives_new_graph_instance(tmp_path):
    path = tmp_path / "conversation.db"
    first = ConversationGraph(str(path))
    await first.remember(
        "conv-rich", "查找订单相关表", needs_clarification=False,
        action="ask_data", params={"layer": "dwd"},
        selected_resources={"table": "dw.dwd_order_detail"},
        last_assistant_turn={"content": "已选择订单明细表"},
        conversation_summary="目标：查订单；分层：DWD",
        query_frame={"metric": "order_count"}, task_status="active",
    )
    restored = await ConversationGraph(str(path)).context("conv-rich")
    assert restored["last_assistant_turn"]["content"] == "已选择订单明细表"
    assert restored["query_frame"] == {"metric": "order_count"}
    assert restored["task_status"] == "active"


async def test_remember_rejects_stale_expected_version(tmp_path):
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    current = await graph.remember("conv-cas", "查订单", needs_clarification=False)
    with pytest.raises(ConversationStateConflictError):
        await graph.remember(
            "conv-cas", "查订单", needs_clarification=False,
            expected_version=current["state_version"] - 1,
        )
```

- [ ] **Step 2: Verify the new tests fail**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short -k "rich_context or stale_expected"`

Expected: missing fields/signature and missing exception failures.

- [ ] **Step 3: Extend state and serialize mutations**

Add to `ConversationState`:

```python
last_assistant_turn: dict[str, Any]
conversation_summary: str
query_frame: dict[str, Any]
task_status: str
```

Add:

```python
class ConversationStateConflictError(RuntimeError):
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("会话状态已经更新，请根据最新状态继续。")
        self.current = current
```

Initialize `self._conversation_locks: defaultdict[str, asyncio.Lock]`. Extend `context()` to return the four fields with empty defaults.

Change `remember()` to accept:

```python
last_assistant_turn: dict[str, Any] | None = None
conversation_summary: str | None = None
query_frame: dict[str, Any] | None = None
task_status: str | None = None
expected_version: int | None = None
```

Inside the conversation lock: reload current state, compare `expected_version`, increment `state_version` once, assign that new version to a pending interaction, update all fields with `aupdate_state()`, and return the new context.

- [ ] **Step 4: Make answers and cancellation atomic**

Wrap `answer()` in the same conversation lock, reload pending state inside the lock, clear it, increment the version, and return `{**resolved, "state_version": next_version}`.

Add:

```python
async def cancel(self, conversation_id: str | None) -> dict[str, Any]:
    if not conversation_id:
        return {}
    await self._ensure_initialized()
    async with self._conversation_locks[conversation_id]:
        current = await self.context(conversation_id)
        next_version = int(current.get("state_version") or 0) + 1
        await self._graph.aupdate_state(
            self._config(conversation_id),
            {"pending_objective": "", "pending_interaction": {},
             "task_status": "cancelled", "state_version": next_version},
            as_node="resolve_context",
        )
        return await self.context(conversation_id)
```

- [ ] **Step 5: Run conversation-state tests**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short -k "interaction or context or state or cancel"`

Expected: existing and new selected tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add dataworks_agent/agent/conversation_graph.py tests/integration/test_agent_interaction.py
git commit -m "feat(dialogue): persist versioned conversation state"
```

---

### Task 3: Unified Mixed Card Response Policy

**Files:**
- Create: `dataworks_agent/agent/response_policy.py`
- Modify: `dataworks_agent/agent/interaction.py:19-179`
- Modify: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Produces: `ConversationMeta`, greeting/clarification/explanation responses, and workflow interaction normalization.

- [ ] **Step 1: Add failing policy tests**

```python
from dataworks_agent.agent.response_policy import ResponsePolicy


def test_greeting_returns_entry_cards():
    data = ResponsePolicy().greeting({}, state_version=1)
    assert [item["id"] for item in data["interaction"]["options"]] == [
        "ask_data", "find_table", "modeling", "diagnose"
    ]


def test_explanation_preserves_active_interaction():
    context = {"pending_interaction": {
        "interaction_id": "int_orders", "type": "single_select",
        "purpose": "select_table", "prompt": "请选择候选表",
        "options": [{"id": "detail", "label": "订单明细表", "value": "dw.detail", "description": "一单一行", "payload": {}}],
        "allow_custom_input": True, "custom_input_placeholder": "",
        "state_version": 2, "status": "pending",
    }}
    message, data = ResponsePolicy().explain(context)
    assert "一单一行" in message
    assert data["interaction"]["interaction_id"] == "int_orders"


def test_string_next_actions_become_structured_options():
    data = ResponsePolicy().normalize_workflow_data(
        {"next_actions": ["查看字段", "查询数据"]},
        purpose="next_step", state_version=5,
    )
    assert [item["label"] for item in data["interaction"]["options"]] == ["查看字段", "查询数据"]
```

- [ ] **Step 2: Verify policy tests fail**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short -k "greeting_returns or explanation_preserves or string_next"`

Expected: missing `ResponsePolicy` failure.

- [ ] **Step 3: Implement response policy**

Create `ConversationMeta` with `Field(default_factory=dict)` for selected resources. Create four entry options with stable IDs `ask_data`, `find_table`, `modeling`, and `diagnose`.

Implement:

```python
class ConversationMeta(BaseModel):
    conversation_id: str = ""
    active_goal: str = ""
    action: str = ""
    status: str = "idle"
    state_version: int = 0
    selected_resources: dict[str, Any] = Field(default_factory=dict)


ENTRY_OPTIONS = [
    {"id": "ask_data", "type": "action", "label": "智能问数", "value": "我想进行智能问数", "description": "查询已确认口径的数据"},
    {"id": "find_table", "type": "action", "label": "查找数据表", "value": "我想查找数据表", "description": "搜索现有数据资产"},
    {"id": "modeling", "type": "action", "label": "数仓建模", "value": "我想进行数仓建模", "description": "生成可审计的建模方案"},
    {"id": "diagnose", "type": "action", "label": "异常排查", "value": "我想排查任务异常", "description": "诊断节点和依赖状态"},
]


class ResponsePolicy:
    def greeting(self, context: dict[str, Any], *, state_version: int) -> dict[str, Any]:
        pending = dict(context.get("pending_interaction") or {})
        if pending:
            return {"interaction": pending}
        return self._build_entry_interaction("你想先做哪件事？", "choose_entry", state_version)

    def explain(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        pending = dict(context.get("pending_interaction") or {})
        descriptions = [
            f"{item.get('label')}：{item.get('description')}"
            for item in pending.get("options") or [] if item.get("description")
        ]
        previous = str((context.get("last_assistant_turn") or {}).get("content") or "")
        return "；".join(descriptions) or f"上一条的意思是：{previous}", {"interaction": pending or None}

    def clarify(self, *, state_version: int) -> dict[str, Any]:
        return self._build_entry_interaction(
            "我还不能确定你指的是哪一步，请选择或补充说明。",
            "clarify_request",
            state_version,
        )

    def normalize_workflow_data(self, data: dict[str, Any], *, purpose: str, state_version: int) -> dict[str, Any]:
        normalized = dict(data)
        raw = normalized.get("option_chips") or normalized.get("next_actions") or []
        normalized["option_chips"] = [
            item if isinstance(item, dict) else {
                "id": f"action_{index}", "type": "action", "label": str(item),
                "value": str(item), "payload": {"value": str(item)},
            }
            for index, item in enumerate(raw) if str(item).strip()
        ]
        interaction = build_interaction(normalized, purpose=purpose, state_version=state_version)
        normalized["interaction"] = interaction.model_dump() if interaction else None
        return normalized

    def _build_entry_interaction(self, prompt: str, purpose: str, state_version: int) -> dict[str, Any]:
        data = {
            "interaction_prompt": prompt,
            "interaction_purpose": purpose,
            "option_chips": ENTRY_OPTIONS,
            "allow_custom_input": True,
            "custom_input_hint": "也可以直接描述你的目标",
        }
        interaction = build_interaction(data, purpose=purpose, state_version=state_version)
        return {"interaction": interaction.model_dump() if interaction else None}

    def conversation_meta(self, conversation_id: str, context: dict[str, Any]) -> dict[str, Any]:
        return ConversationMeta(
            conversation_id=conversation_id,
            active_goal=str(context.get("objective") or ""),
            action=str(context.get("action") or ""),
            status=str(context.get("task_status") or "idle"),
            state_version=int(context.get("state_version") or 0),
            selected_resources=dict(context.get("selected_resources") or {}),
        ).model_dump()
```

Rules:

- greeting with an active interaction returns the same interaction;
- greeting without a task returns entry cards plus custom input;
- explanation uses option descriptions and preserves the same interaction;
- `next_actions` strings become `{id, type:"action", label, value, payload}` objects;
- no useful option means no fake card.

- [ ] **Step 4: Normalize action payloads in `interaction.py`**

Add to `_option_payload()`:

```python
if option_type == "action":
    action_value = str(value or "").strip()
    return {"value": action_value, "params": {"follow_up_action": action_value}}
```

Update `build_interaction()` so legacy strings are converted rather than discarded. Preserve existing `pick_table` full identifiers unchanged.

- [ ] **Step 5: Run interaction tests**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add dataworks_agent/agent/response_policy.py dataworks_agent/agent/interaction.py tests/integration/test_agent_interaction.py
git commit -m "feat(dialogue): centralize mixed card responses"
```

---
### Task 4: Integrate Resolver, State, and Policy in ChatAgent

**Files:**
- Modify: `dataworks_agent/agent/core.py:84-686`
- Modify: `tests/integration/test_agent_interaction.py`
- Modify: `tests/integration/test_context_resolver.py`

**Interfaces:**
- Consumes: `ContextResolver`, `ResponsePolicy`, and version-aware `ConversationGraph` methods.
- Produces: one `ChatAgent.chat()` path that persists contextual turns and no longer depends on `_query_frames`.

- [ ] **Step 1: Add failing ChatAgent journey tests**

```python
async def test_greeting_emits_and_persists_entry_cards(tmp_path):
    agent = ChatAgent()
    agent._conversation_graph = ConversationGraph(str(tmp_path / "conversation.db"))
    response = await agent.chat("你好", conversation_id="conv-greeting")
    assert response.data["interaction"]["purpose"] == "choose_entry"
    restored = await agent.get_conversation_context("conv-greeting")
    assert restored["pending_interaction"]["purpose"] == "choose_entry"


async def test_explain_preserves_current_interaction(tmp_path):
    agent = ChatAgent()
    agent._conversation_graph = ConversationGraph(str(tmp_path / "conversation.db"))
    await agent._conversation_graph.remember(
        "conv-explain", "查找订单相关表", needs_clarification=True,
        action="ask_data",
        pending_interaction={
            "interaction_id": "int_orders", "type": "single_select",
            "purpose": "select_table", "prompt": "请选择候选表",
            "options": [{"id": "detail", "label": "订单明细表", "value": "dw.detail", "description": "一单一行", "payload": {}}],
            "allow_custom_input": True, "custom_input_placeholder": "",
            "state_version": 1, "status": "pending",
        },
        last_assistant_turn={"content": "请选择订单表"},
    )
    response = await agent.chat("什么意思", conversation_id="conv-explain")
    assert "一单一行" in response.message
    assert response.data["interaction"]["interaction_id"] == "int_orders"


async def test_query_frame_survives_new_agent_instance(tmp_path):
    path = tmp_path / "conversation.db"
    first = ChatAgent()
    first._conversation_graph = ConversationGraph(str(path))
    await first._conversation_graph.remember(
        "conv-query", "查询订单量", needs_clarification=False,
        query_frame={"metric": "order_count", "filters": {"layer": "dwd"}},
    )
    second = ChatAgent()
    second._conversation_graph = ConversationGraph(str(path))
    assert (await second.get_conversation_context("conv-query"))["query_frame"]["metric"] == "order_count"
```

- [ ] **Step 2: Verify current behavior fails**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short -k "greeting_emits or explain_preserves or query_frame_survives"`

Expected: greeting lacks cards, explanation does not preserve the interaction, or query context remains process-local.

- [ ] **Step 3: Initialize the resolver and policy and remove process memory**

In `ChatAgent.__init__()`:

```python
self._context_resolver = ContextResolver(LLMDialogueFallback())
self._response_policy = ResponsePolicy()
```

Delete `_query_frames`, `_query_frame_ttl_seconds`, `_query_frame_capacity`, and `_prune_query_frames()`. Read and write query frame data through `ConversationGraph.context()` and `remember()`.

- [ ] **Step 4: Resolve every turn before NLU**

After loading `previous_context`:

```python
resolved_turn = await self._context_resolver.resolve(incoming_message, previous_context)
answer = answer or resolved_turn.interaction_answer
merged_context_updates = self._merge_context_updates(
    dict(context_updates or {}), resolved_turn.context_updates,
)
```

Add explicit branches before NLU:

```python
if resolved_turn.dialogue_action is DialogueAction.CANCEL:
    context = await self._conversation_graph.cancel(conversation_id)
    return await self._complete_turn(
        conversation_id, incoming_message,
        ChatResponse(message="已取消当前任务。", success=True, data={"agent_mode": "cancelled"}),
        context=context,
    )

if resolved_turn.dialogue_action is DialogueAction.GREETING:
    data = self._response_policy.greeting(
        previous_context,
        state_version=int(previous_context.get("state_version") or 0) + 1,
    )
    message = "你好，我们可以继续当前任务。" if previous_context.get("objective") else "你好！我可以协助你查表、问数、建模和排障。"
    return await self._complete_turn(
        conversation_id, incoming_message,
        ChatResponse(message=message, success=True, data={"agent_mode": "greeting", **data}),
        context=previous_context,
    )

if resolved_turn.dialogue_action is DialogueAction.EXPLAIN:
    message, data = self._response_policy.explain(previous_context)
    return await self._complete_turn(
        conversation_id, incoming_message,
        ChatResponse(message=message, success=True, data={"agent_mode": "explain", **data}),
        context=previous_context,
    )
```

Use `resolved_turn.rewritten_message` for NLU and workflow execution. `RESET` is handled by the frontend creating a new conversation ID; a textual reset clears only the server state for the current ID.

- [ ] **Step 5: Add one completion helper used by every return path**

```python
async def _complete_turn(
    self,
    conversation_id: str | None,
    incoming_message: str,
    response: ChatResponse,
    *,
    context: dict[str, Any] | None = None,
) -> ChatResponse:
    if not conversation_id:
        return response
    current = context or await self._conversation_graph.context(conversation_id)
    interaction = response.data.get("interaction") if isinstance(response.data, dict) else None
    remembered = await self._conversation_graph.remember(
        conversation_id,
        str(current.get("objective") or incoming_message),
        needs_clarification=bool(interaction),
        action=str(current.get("action") or ""),
        params=dict(current.get("params") or {}),
        workflow_state=dict(current.get("workflow_state") or {}),
        pending_interaction=dict(interaction or {}) if interaction is not None else None,
        selected_resources=dict(current.get("selected_resources") or {}),
        last_result=dict(response.data or {}),
        last_assistant_turn={"content": response.message, "payload": dict(response.data or {})},
        conversation_summary=str(current.get("conversation_summary") or ""),
        query_frame=dict(current.get("query_frame") or {}),
        task_status="waiting_user" if interaction else "active",
    )
    response.data["conversation"] = self._response_policy.conversation_meta(conversation_id, remembered)
    self._save_conversation_message(conversation_id, "assistant", response.message, payload=response.data)
    return response
```

Remove old assistant-message saves so every assistant turn is persisted exactly once.

- [ ] **Step 6: Normalize workflow output before completion**

```python
current = await self._conversation_graph.context(conversation_id)
data = self._response_policy.normalize_workflow_data(
    workflow.to_data(),
    purpose=self._interaction_purpose(workflow.to_data(), intent.action),
    state_version=int(current.get("state_version") or 0) + 1,
)
```

For `CLARIFY`, return `ResponsePolicy.clarify()` without planning. For `ANSWER`, call `ConversationGraph.answer()` before constructing the rewritten workflow request. Preserve full selected resources returned by the chosen option.

- [ ] **Step 7: Run backend dialogue tests**

Run: `uv run python -m pytest tests/integration/test_context_resolver.py tests/integration/test_agent_interaction.py -q --tb=short`

Expected: both files pass.

- [ ] **Step 8: Commit Task 4**

```powershell
git add dataworks_agent/agent/core.py tests/integration/test_agent_interaction.py tests/integration/test_context_resolver.py
git commit -m "feat(dialogue): integrate contextual multi-turn orchestration"
```

---

### Task 5: Chat and History API Contract

**Files:**
- Modify: `dataworks_agent/routers/agent.py:43-160`
- Modify: `tests/integration/test_agent_api.py`

**Interfaces:**
- Produces: stable `data.conversation`, `data.interaction`, and history `conversation` payloads for the frontend.

- [ ] **Step 1: Add failing API contract tests**

```python
def test_messages_returns_full_conversation_envelope(client, monkeypatch):
    monkeypatch.setattr(agent_router._agent, "get_conversation_history", lambda *_: [])
    async def fake_context(_):
        return {
            "objective": "查订单", "action": "ask_data",
            "task_status": "waiting_user", "state_version": 7,
            "selected_resources": {"table": "dw.orders"},
            "pending_interaction": {"interaction_id": "int_7", "status": "pending"},
        }
    monkeypatch.setattr(agent_router._agent, "get_conversation_context", fake_context)
    payload = client.get("/agent/messages?conversation_id=conv-1").json()
    assert payload["conversation"]["active_goal"] == "查订单"
    assert payload["active_interaction"]["interaction_id"] == "int_7"


def test_expired_answer_returns_latest_server_state(client, monkeypatch):
    async def fake_chat(*args, **kwargs):
        return AgentChatResponse(
            message="当前候选已经更新，请根据最新选项继续。",
            success=False,
            data={
                "interaction": {"interaction_id": "int_latest", "status": "pending", "state_version": 9},
                "conversation": {"conversation_id": "conv-1", "state_version": 9},
            },
            error="interaction_expired",
        )
    monkeypatch.setattr(agent_router._agent, "chat", fake_chat)
    payload = client.post("/agent/chat", json={"message": "第二个", "conversation_id": "conv-1"}).json()
    assert payload["data"]["interaction"]["interaction_id"] == "int_latest"
```

- [ ] **Step 2: Verify the history contract fails**

Run: `uv run python -m pytest tests/integration/test_agent_api.py -q --tb=short`

Expected: the new `conversation` assertion fails.

- [ ] **Step 3: Return the conversation envelope**

In `get_messages()`:

```python
conversation = {
    "conversation_id": conversation_id,
    "active_goal": str(context.get("objective") or ""),
    "action": str(context.get("action") or ""),
    "status": str(context.get("task_status") or "idle"),
    "state_version": int(context.get("state_version") or 0),
    "selected_resources": dict(context.get("selected_resources") or {}),
}
return {
    "messages": messages,
    "active_interaction": context.get("pending_interaction") or None,
    "state_version": conversation["state_version"],
    "conversation": conversation,
}
```

HTTP and WebSocket responses must use the same `ChatResponse.data` structure. Keep interaction-expired responses as structured `success=false` payloads so the frontend can apply the latest state.

- [ ] **Step 4: Run API tests**

Run: `uv run python -m pytest tests/integration/test_agent_api.py -q --tb=short`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add dataworks_agent/routers/agent.py tests/integration/test_agent_api.py
git commit -m "feat(api): expose recoverable conversation envelope"
```

---

### Task 6: Frontend Interaction Lifecycle and Recovery

**Files:**
- Modify: `frontend/src/components/agent/chatInteraction.ts`
- Modify: `frontend/src/components/agent/MessageBubble.vue`
- Modify: `frontend/src/pages/SmartChatPage.vue:250-500`
- Create: `frontend/src/__tests__/conversationLifecycle.spec.ts`
- Modify: `frontend/src/__tests__/structuredInteraction.spec.ts`
- Modify: `frontend/src/__tests__/agentChatCompatibility.spec.ts`

**Interfaces:**
- Consumes: backend conversation and interaction envelopes.
- Produces: `ConversationMeta`, `reconcileActiveInteraction()`, and stable stale/restart behavior.

- [ ] **Step 1: Add failing lifecycle helper tests**

```typescript
import { describe, expect, it } from 'vitest'
import {
  reconcileActiveInteraction,
  type AgentInteraction,
  type InteractionMessage,
} from '../components/agent/chatInteraction'

const active: AgentInteraction = {
  interaction_id: 'int_orders', type: 'single_select', purpose: 'select_table',
  prompt: '请选择候选表',
  options: [{ id: 'detail', label: '订单明细表', value: 'dw.detail', payload: {} }],
  allow_custom_input: true, custom_input_placeholder: '', state_version: 4, status: 'pending',
}

it('keeps only the newest copy clickable', () => {
  const messages: InteractionMessage[] = [
    { id: 'old', role: 'assistant', interaction: { ...active } },
    { id: 'new', role: 'assistant', interaction: { ...active } },
  ]
  const result = reconcileActiveInteraction(messages, active)
  expect(result[0].interaction?.status).toBe('expired')
  expect(result[1].interaction?.status).toBe('pending')
})
```

- [ ] **Step 2: Verify the helper is missing**

Run: `Set-Location frontend; npm run test:unit -- --run src/__tests__/conversationLifecycle.spec.ts`

Expected: missing export failure.

- [ ] **Step 3: Add shared types and reconciliation helper**

```typescript
export interface ConversationMeta {
  conversation_id: string
  active_goal: string
  action: string
  status: string
  state_version: number
  selected_resources: Record<string, unknown>
}

export interface InteractionMessage {
  id: string
  role: 'user' | 'assistant'
  interaction?: AgentInteraction
  [key: string]: unknown
}

export function reconcileActiveInteraction<T extends InteractionMessage>(
  messages: T[], active: AgentInteraction | null | undefined,
): T[] {
  const next = messages.map(message => ({ ...message }))
  if (!active) return next
  let target = -1
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index].role === 'assistant') {
      target = index
      if (next[index].interaction?.interaction_id === active.interaction_id) break
    }
  }
  next.forEach((message, index) => {
    if (message.interaction?.interaction_id === active.interaction_id) {
      message.interaction = { ...message.interaction, status: index === target ? 'pending' : 'expired' }
    }
  })
  if (target >= 0) next[target].interaction = { ...active, status: 'pending' }
  return next
}
```

- [ ] **Step 4: Apply server state to normal, answer, stale, and restored responses**

In `SmartChatPage.vue`, add `conversationMeta` and one `applyAgentResponse()` helper. It updates the assistant message, calls `reconcileActiveInteraction()`, updates `activeInteractionId`, and saves `response.data.conversation`.

For `interaction_expired` and `state_conflict`, apply the returned latest interaction instead of restoring the stale local copy. In `loadConversationHistory()`:

```typescript
messages.value = reconcileActiveInteraction(restored, data.active_interaction)
conversationMeta.value = data.conversation ?? null
activeInteractionId.value = data.active_interaction?.interaction_id ?? null
```

- [ ] **Step 5: Render pending, answered, and expired states**

In `MessageBubble.vue`, disable options unless `interaction.status === 'pending'`. Show `等待回答`, `已回答`, or `已失效`; keep inactive cards visible for context. Preserve custom-input behavior only for the active card.

- [ ] **Step 6: Run frontend interaction tests**

Run:

```powershell
Set-Location frontend
npm run test:unit -- --run src/__tests__/conversationLifecycle.spec.ts src/__tests__/structuredInteraction.spec.ts src/__tests__/agentChatInteraction.spec.ts src/__tests__/agentChatCompatibility.spec.ts
```

Expected: all selected tests pass.

- [ ] **Step 7: Run frontend build**

Run: `Set-Location frontend; npm run build`

Expected: TypeScript and Vite build exit 0.

- [ ] **Step 8: Commit Task 6**

```powershell
git add frontend/src/components/agent/chatInteraction.ts frontend/src/components/agent/MessageBubble.vue frontend/src/pages/SmartChatPage.vue frontend/src/__tests__/conversationLifecycle.spec.ts frontend/src/__tests__/structuredInteraction.spec.ts frontend/src/__tests__/agentChatCompatibility.spec.ts
git commit -m "feat(frontend): recover active dialogue interactions"
```

---
### Task 7: Correlated Conversation Event Logs

**Files:**
- Create: `dataworks_agent/agent/conversation_events.py`
- Modify: `dataworks_agent/eventlog/store.py:84-197`
- Modify: `dataworks_agent/main.py:34-55`
- Modify: `dataworks_agent/routers/logs.py`
- Modify: `dataworks_agent/agent/core.py`
- Create: `tests/integration/test_conversation_events.py`
- Modify: `tests/integration/test_agent_api.py`

**Interfaces:**
- Produces: `ConversationEventRecorder`, rotating `conversation-events.jsonl`, and `GET /logs/conversations`.

- [ ] **Step 1: Add failing recorder order and masking tests**

```python
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import dataworks_agent.db.models
from dataworks_agent.agent.conversation_events import ConversationEventRecorder
from dataworks_agent.db.database import Base
from dataworks_agent.eventlog.store import EventLog


@pytest.fixture
def db_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_recorder_persists_ordered_masked_events(db_session_factory):
    recorder = ConversationEventRecorder(EventLog(db_session_factory))
    trace = recorder.start_turn("conv-log", request_id="req-1", input_text="你好")
    recorder.emit(trace, "context_loaded", state_version_before=2, authorization="Bearer secret")
    recorder.emit(trace, "turn_classified", dialogue_action="greeting", confidence=1.0)
    events = recorder.events(conversation_id="conv-log")
    assert [item["event"] for item in events] == ["turn_received", "context_loaded", "turn_classified"]
    serialized = json.dumps(events, ensure_ascii=False)
    assert "Bearer secret" not in serialized
    assert "***" in serialized
```


- [ ] **Step 2: Verify the recorder module is missing**

Run: `uv run python -m pytest tests/integration/test_conversation_events.py -q --tb=short`

Expected: missing module failure.

- [ ] **Step 3: Allow caller-owned turn IDs in EventLog**

Change `EventLog.create_run()`:

```python
def create_run(
    self, session_id: str, *, run_id: str | None = None,
    channel: str = "", actor_user_id: str = "", actor_team: str = "",
    actor_org_code: str = "", created_by_ip: str = "", status: str = "submitted",
) -> str:
    run_id = run_id or f"run_{uuid.uuid4().hex}"
    # retain the existing insert and return behavior
```

- [ ] **Step 4: Implement the recorder**

```python
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from dataworks_agent.eventlog.masking import mask_payload
from dataworks_agent.eventlog.store import EventLog

logger = logging.getLogger("dataworks_agent.conversation")


@dataclass(frozen=True)
class TurnTrace:
    conversation_id: str
    request_id: str
    turn_id: str
    started_at: float


class ConversationEventRecorder:
    def __init__(self, event_log: EventLog | None = None) -> None:
        self._event_log = event_log or EventLog()

    def start_turn(self, conversation_id: str, *, request_id: str | None = None, input_text: str = "") -> TurnTrace:
        trace = TurnTrace(
            conversation_id=conversation_id,
            request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
            turn_id=f"turn_{uuid.uuid4().hex[:12]}",
            started_at=time.monotonic(),
        )
        self._event_log.create_run(conversation_id, run_id=trace.turn_id, channel="web", status="running")
        self.emit(trace, "turn_received", input_length=len(input_text))
        return trace

    def emit(self, trace: TurnTrace, event: str, **payload: Any) -> None:
        body = mask_payload({
            "event": event, "request_id": trace.request_id,
            "conversation_id": trace.conversation_id, "turn_id": trace.turn_id,
            **payload,
        })
        self._event_log.append(
            run_id=trace.turn_id, session_id=trace.conversation_id,
            event_type=event, payload=body,
        )
        logger.info("conversation_event", extra={"conversation_event": body})

    def finish(self, trace: TurnTrace, *, success: bool, **payload: Any) -> None:
        self.emit(
            trace, "response_sent",
            outcome="success" if success else "failed",
            duration_ms=int((time.monotonic() - trace.started_at) * 1000),
            **payload,
        )
        self._event_log.update_run(trace.turn_id, status="completed" if success else "failed")

    def events(self, *, conversation_id: str) -> list[dict[str, Any]]:
        return [{"seq": item.seq, "created_at": item.created_at, **item.payload}
                for item in self._event_log.events_by_session(conversation_id)]
```

- [ ] **Step 5: Configure a dedicated rotating JSONL handler**

Add to `main.py`:

```python
class ConversationJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json
        payload = getattr(record, "conversation_event", None)
        return json.dumps(payload or {"event": "log", "message": record.getMessage()}, ensure_ascii=False)
```

Attach a `RotatingFileHandler` for `log/conversation-events.jsonl`, `10 MiB`, five backups, UTF-8, to logger `dataworks_agent.conversation` with `propagate=False`. Tag handlers to prevent duplicates during reloads/tests.

- [ ] **Step 6: Emit the required event chain from ChatAgent**

Emit these events at their actual boundaries:

```text
turn_received
context_loaded
turn_classified
reference_resolved
nlu_parsed
workflow_started
workflow_finished
interaction_emitted
state_persisted
response_sent
```

Exception paths emit `turn_failed` with `failure_stage`, `error_type`, `state_version`, and `write_workflow_started`. Use `logger.exception` for the full stack. Add `request_id` and `turn_id` to `response.data.conversation` for support correlation.

- [ ] **Step 7: Add filtered query API**

Add `GET /logs/conversations` accepting:

```python
conversation_id: str
request_id: str | None
turn_id: str | None
interaction_id: str | None
event: str | None
level: str | None
created_from: str | None
created_to: str | None
limit: int = Query(500, ge=1, le=5000)
```

Load `ConversationEventRecorder().events(conversation_id=conversation_id)`, apply the declared exact filters, and return chronological `events`. Parse ISO dates into UTC before time comparisons.

- [ ] **Step 8: Run event and API tests**

Run: `uv run python -m pytest tests/integration/test_conversation_events.py tests/integration/test_agent_api.py -q --tb=short`

Expected: all tests pass and fixture secrets are masked.

- [ ] **Step 9: Commit Task 7**

```powershell
git add dataworks_agent/agent/conversation_events.py dataworks_agent/eventlog/store.py dataworks_agent/main.py dataworks_agent/routers/logs.py dataworks_agent/agent/core.py tests/integration/test_conversation_events.py tests/integration/test_agent_api.py
git commit -m "feat(observability): trace every conversation turn"
```

---

### Task 8: Backend Journeys, Restart, Concurrency, and 50 Turns

**Files:**
- Create: `tests/integration/test_continuous_dialogue_journeys.py`
- Modify: `dataworks_agent/scripts/test_continuous_dialogue.py`

**Interfaces:**
- Produces: deterministic no-write workflow fake, eight backend journeys, 50-turn stability coverage, and an assertion-based HTTP verifier.

- [ ] **Step 1: Add a deterministic no-write workflow fake**

```python
from dataworks_agent.agent.workflow_service import WorkflowResult


class DeterministicWorkflowService:
    writes = 0

    async def execute(self, *, message, action, params, execution_mode, initialize_data, publish, client_ip):
        if "订单" in message and not params.get("selected_resources"):
            return WorkflowResult(
                success=True, message="找到了订单候选表。",
                workflow_type="ask_data", mode="plan",
                data={
                    "clarifying_questions": ["请选择订单表"],
                    "option_chips": [
                        {"id": "detail", "type": "pick_table", "label": "订单明细表", "value": "dw.dwd_order_detail", "description": "一单一行"},
                        {"id": "summary", "type": "pick_table", "label": "订单汇总表", "value": "dw.dws_order_summary", "description": "按日期聚合"},
                    ],
                },
            )
        return WorkflowResult(
            success=True, message="已根据当前上下文继续。",
            workflow_type=action, mode="plan",
            data={"next_actions": ["查看字段", "查询数据", "分析血缘"]},
        )
```

Reset `writes` in a fixture. The fake exposes no DataWorks client.

- [ ] **Step 2: Add the primary multi-turn journey**

```python
async def test_greeting_search_explain_select_continue_journey(tmp_path):
    agent = ChatAgent()
    agent._conversation_graph = ConversationGraph(str(tmp_path / "conversation.db"))
    agent._workflow_service = DeterministicWorkflowService()

    greeting = await agent.chat("你好", conversation_id="journey-1")
    assert greeting.data["interaction"]["purpose"] == "choose_entry"

    search = await agent.chat("我想查一下订单", conversation_id="journey-1")
    interaction_id = search.data["interaction"]["interaction_id"]

    explanation = await agent.chat("什么意思", conversation_id="journey-1")
    assert explanation.data["interaction"]["interaction_id"] == interaction_id
    assert "按日期聚合" in explanation.message

    selected = await agent.chat("第二个", conversation_id="journey-1")
    assert selected.data["conversation"]["selected_resources"]["table"] == "dw.dws_order_summary"

    continued = await agent.chat("继续", conversation_id="journey-1")
    assert continued.data["interaction"]["options"]
    assert agent._workflow_service.writes == 0
```

- [ ] **Step 3: Add seven boundary journeys**

Create separate tests with concrete assertions:

```python
def build_test_agent(path) -> ChatAgent:
    agent = ChatAgent()
    agent._conversation_graph = ConversationGraph(str(path))
    agent._workflow_service = DeterministicWorkflowService()
    return agent


async def test_refresh_and_new_agent_restore_pending_card(tmp_path):
    path = tmp_path / "restart.db"
    first = build_test_agent(path)
    response = await first.chat("我想查一下订单", conversation_id="journey-restart")
    interaction_id = response.data["interaction"]["interaction_id"]
    second = build_test_agent(path)
    restored = await second.get_conversation_context("journey-restart")
    assert restored["pending_interaction"]["interaction_id"] == interaction_id
    selected = await second.chat("第二个", conversation_id="journey-restart")
    assert selected.data["conversation"]["selected_resources"]["table"] == "dw.dws_order_summary"


async def test_task_switch_does_not_leak_old_layer_or_resource(tmp_path):
    agent = build_test_agent(tmp_path / "switch.db")
    await agent.chat("我想查一下订单", conversation_id="journey-switch")
    await agent.chat("第二个", conversation_id="journey-switch")
    response = await agent.chat("换一个话题，排查凌晨失败的节点", conversation_id="journey-switch")
    assert response.data["conversation"]["active_goal"].startswith("换一个话题")
    assert response.data["conversation"]["selected_resources"] == {}


async def test_two_concurrent_answers_only_consume_once(tmp_path):
    agent = build_test_agent(tmp_path / "concurrent.db")
    await agent.chat("我想查一下订单", conversation_id="journey-concurrent")
    results = await asyncio.gather(
        agent.chat("第一个", conversation_id="journey-concurrent"),
        agent.chat("第二个", conversation_id="journey-concurrent"),
    )
    assert sum(item.success for item in results) == 1
    assert {item.error for item in results if not item.success} <= {"interaction_expired", "state_conflict"}


async def test_greeting_mid_task_preserves_pending_card(tmp_path):
    agent = build_test_agent(tmp_path / "greeting.db")
    search = await agent.chat("我想查一下订单", conversation_id="journey-greeting")
    interaction_id = search.data["interaction"]["interaction_id"]
    greeting = await agent.chat("你好", conversation_id="journey-greeting")
    assert greeting.data["interaction"]["interaction_id"] == interaction_id
    assert (await agent.get_conversation_context("journey-greeting"))["objective"] == "我想查一下订单"


async def test_layer_date_and_plan_mode_accumulate(tmp_path):
    agent = build_test_agent(tmp_path / "modify.db")
    await agent.chat("我想查一下订单", conversation_id="journey-modify")
    await agent.chat("只看 DWD", conversation_id="journey-modify")
    await agent.chat("再加上最近七天", conversation_id="journey-modify")
    response = await agent.chat("不要执行，只生成方案", conversation_id="journey-modify")
    params = (await agent.get_conversation_context("journey-modify"))["params"]
    assert params["layer"] == "dwd"
    assert params["date_range"] == "last_7_days"
    assert params["execution_mode"] == "plan"
    assert response.success is True


async def test_cancel_clears_pending_but_keeps_objective(tmp_path):
    agent = build_test_agent(tmp_path / "cancel.db")
    await agent.chat("我想查一下订单", conversation_id="journey-cancel")
    cancelled = await agent.chat("取消这个任务", conversation_id="journey-cancel")
    context = await agent.get_conversation_context("journey-cancel")
    assert cancelled.data["conversation"]["status"] == "cancelled"
    assert context["pending_interaction"] == {}
    assert context["objective"] == "我想查一下订单"


async def test_ambiguous_ordinal_without_card_returns_clarification(tmp_path):
    agent = build_test_agent(tmp_path / "clarify.db")
    response = await agent.chat("第二个", conversation_id="journey-clarify")
    assert response.data["interaction"]["purpose"] == "clarify_request"
    assert response.data["interaction"]["allow_custom_input"] is True
```

For concurrency:

```python
results = await asyncio.gather(
    agent.chat("第一个", conversation_id="journey-concurrent"),
    agent.chat("第二个", conversation_id="journey-concurrent"),
)
assert sum(item.success for item in results) == 1
assert {item.error for item in results if not item.success} <= {"interaction_expired", "state_conflict"}
```

- [ ] **Step 4: Add a 50-turn bounded-state test**

```python
async def test_fifty_turns_keep_state_bounded_and_versions_monotonic(tmp_path):
    agent = ChatAgent()
    agent._conversation_graph = ConversationGraph(str(tmp_path / "conversation.db"))
    agent._workflow_service = DeterministicWorkflowService()
    versions = []
    for message in ["你好", "我想查一下订单", "什么意思", "第二个", "继续"] * 10:
        response = await agent.chat(message, conversation_id="journey-50")
        versions.append(response.data["conversation"]["state_version"])
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    context = await agent.get_conversation_context("journey-50")
    assert len(context["conversation_summary"]) <= 4000
    assert DeterministicWorkflowService.writes == 0
```

- [ ] **Step 5: Run backend journeys**

Run: `uv run python -m pytest tests/integration/test_continuous_dialogue_journeys.py -q --tb=short`

Expected: eight journeys plus the 50-turn test pass.

- [ ] **Step 6: Replace print-only verifier with assertions and reports**

Refactor `dataworks_agent/scripts/test_continuous_dialogue.py` to use:

```python
@dataclass
class TurnResult:
    index: int
    request: dict[str, Any]
    response: dict[str, Any]
    passed: bool
    assertions: list[str]


def require(condition: bool, message: str) -> str:
    if not condition:
        raise AssertionError(message)
    return message
```

Run the approved journey over HTTP, collect every request/response, fetch `/logs/conversations`, and write:

```text
reports/continuous-dialogue/<UTC-run-id>/
├── summary.md
├── conversation-transcript.json
├── backend-events.jsonl
└── failures/
```

Exit 1 on a failed assertion or missing `turn_received`, `context_loaded`, `turn_classified`, `state_persisted`, or `response_sent` event.

- [ ] **Step 7: Commit Task 8**

```powershell
git add tests/integration/test_continuous_dialogue_journeys.py dataworks_agent/scripts/test_continuous_dialogue.py
git commit -m "test(dialogue): add multi-turn and stability journeys"
```

---

### Task 9: Real Browser Journeys and Complete Report Bundle

**Files:**
- Create: `tests/e2e/dialogue_server.py`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/continuous-dialogue.spec.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: real FastAPI router, real ChatAgent dialogue code, deterministic no-write workflow fake, and real Vue page.
- Produces: eight browser journeys, screenshots, frontend console/network logs, and report artifacts.

- [ ] **Step 1: Create the deterministic full-stack server**

```python
from __future__ import annotations

import os
import uvicorn

from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.main import app
from dataworks_agent.routers import agent as agent_router
from tests.integration.test_continuous_dialogue_journeys import DeterministicWorkflowService

agent = ChatAgent()
agent._workflow_service = DeterministicWorkflowService()
agent_router._agent = agent
assert agent._workflow_service.writes == 0

if __name__ == "__main__":
    os.environ["ENV"] = "test"
    uvicorn.run(app, host="127.0.0.1", port=8085, log_level="info")
```

Mount a test-only restart endpoint in this file, not production `main.py`; it replaces `agent_router._agent` with a fresh `ChatAgent` using the same checkpoint path.

- [ ] **Step 2: Configure Playwright**

```typescript
import { defineConfig } from '@playwright/test'

process.env.VITE_PROXY_TARGET = 'http://127.0.0.1:8085'

export default defineConfig({
  testDir: './e2e', timeout: 60_000, fullyParallel: false, workers: 1,
  reporter: [['list'], ['junit', { outputFile: '../reports/continuous-dialogue/playwright-results.xml' }]],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'retain-on-failure',
  },
  webServer: [
    { command: 'uv run python ../tests/e2e/dialogue_server.py', url: 'http://127.0.0.1:8085/api/system/health', reuseExistingServer: false, timeout: 120_000 },
    { command: 'npm run dev -- --host 127.0.0.1', url: 'http://127.0.0.1:5173', reuseExistingServer: false, timeout: 120_000 },
  ],
})
```

Confirm the health URL from mounted routes and use that exact route.

- [ ] **Step 3: Collect browser console and network events**

In `continuous-dialogue.spec.ts`, create a UTC run ID and `reports/continuous-dialogue/<run-id>/screenshots`. Register `page.on('console')` and `page.on('response')`; keep only `/agent/` network events. Write `frontend-console.json` and `network-events.json` in `test.afterEach`. Fail if an unallowlisted console `error` exists.

- [ ] **Step 4: Implement the primary browser journey**

```typescript
test('greeting to explanation to second option to continue', async ({ page }) => {
  await page.goto('/')
  const input = page.getByPlaceholder('继续对话...')
  await input.fill('你好'); await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '查找数据表' })).toBeVisible()
  await input.fill('我想查一下订单'); await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '订单汇总表' })).toBeVisible()
  await input.fill('什么意思'); await page.keyboard.press('Enter')
  await expect(page.getByText('按日期聚合')).toBeVisible()
  await input.fill('第二个'); await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '查看字段' })).toBeVisible()
  await input.fill('继续'); await page.keyboard.press('Enter')
})
```

Confirm the actual placeholder before implementation and use its exact text.

- [ ] **Step 5: Add seven browser boundary journeys**

Add tests for:

1. layer + date + plan-only accumulation;
2. cancel preserves history and disables card;
3. refresh restores pending card;
4. backend restart restores pending card;
5. two tabs reject a stale card;
6. new goal does not inherit old resource;
7. ambiguous `第二个` without an active card returns clarification.

Each test performs 5–10 user turns and takes a final screenshot. The two-tab test copies the same `conversation_id` localStorage value before loading the second page.

- [ ] **Step 6: Run browser journeys**

Run: `Set-Location frontend; npm run test:e2e`

Expected: eight Playwright tests pass and no live DataWorks request appears in `network-events.json`.

- [ ] **Step 7: Verify report artifacts**

Run: `Get-ChildItem reports\continuous-dialogue -Recurse | Select-Object FullName,Length`

Expected: `summary.md`, transcript, backend JSONL, frontend console, network events, JUnit XML, and screenshots exist.

- [ ] **Step 8: Commit Task 9**

```powershell
git add tests/e2e/dialogue_server.py frontend/playwright.config.ts frontend/e2e/continuous-dialogue.spec.ts frontend/package.json
git commit -m "test(e2e): verify continuous dialogue in browser"
```

---

### Task 10: Full Regression, Documentation, and Completion Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/product/conversational-dialog-design.md`
- Modify: `docs/superpowers/specs/2026-07-18-strong-continuous-dialogue-design.md` only when implementation reveals a factual mismatch
- Generate but do not commit sensitive artifacts under `reports/continuous-dialogue/<run-id>/`

**Interfaces:**
- Produces: synchronized documentation and the only acceptable completion evidence.

- [ ] **Step 1: Document the implemented contract**

Document exact available behavior:

```text
- Contextual actions: answer, continue, explain, modify, refer, cancel, greeting, reset.
- One pending interaction per conversation, versioned by state_version.
- GET /agent/messages restores conversation metadata and active interaction.
- GET /logs/conversations exports correlated turn events.
- Greeting and explanation preserve an active task.
- Automated verification performs no DataWorks writes.
```

Do not describe behavior that did not pass tests.

- [ ] **Step 2: Run Ruff**

Run: `uv run ruff check .`

Expected: exit 0.

- [ ] **Step 3: Run the full backend integration suite**

Run: `uv run python -m pytest tests/integration/ -q --tb=short`

Expected: all tests pass and `reports/junit.xml` exists.

- [ ] **Step 4: Run all frontend tests**

Run: `Set-Location frontend; npm run test:unit`

Expected: all Vitest files pass.

- [ ] **Step 5: Run frontend build**

Run: `Set-Location frontend; npm run build`

Expected: TypeScript and Vite build exit 0.

- [ ] **Step 6: Run all browser journeys**

Run: `Set-Location frontend; npm run test:e2e`

Expected: all eight journeys pass.

- [ ] **Step 7: Run the HTTP verifier**

Run: `uv run python -m dataworks_agent.scripts.test_continuous_dialogue`

Expected: exit 0 and a new report directory.

- [ ] **Step 8: Inspect logs for failures and secrets**

```powershell
$run = Get-ChildItem reports\continuous-dialogue -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content ($run.FullName + '\backend-events.jsonl') | Select-String -Pattern 'Traceback|Bearer |ALIYUN_ACCESS_KEY|COOKIE|error' -CaseSensitive:$false
Get-Content ($run.FullName + '\frontend-console.json') | Select-String -Pattern 'error|unhandled|failed' -CaseSensitive:$false
```

Expected: no secret, unexplained traceback, or unexplained browser error. Record any intentional test error with its exact event and reason in `summary.md`.

- [ ] **Step 9: Record the no-write safety proof**

```markdown
## Safety

- Real DataWorks folder creation: 0
- Real DataWorks node creation/update/deletion: 0
- Real DataWorks deployment/publish: 0
- External workflow provider: deterministic no-write test provider
```

Cross-check the fake provider counter and browser network log.

- [ ] **Step 10: Complete the report gate**

```markdown
## Completion Gate

- [x] Backend integration suite
- [x] Frontend unit suite
- [x] Frontend build
- [x] Ruff
- [x] Eight browser journeys
- [x] Fifty-turn stability test
- [x] Refresh recovery
- [x] Backend restart recovery
- [x] Concurrent stale-card rejection
- [x] No unexplained browser console errors
- [x] Correlated backend event log reviewed
- [x] No unauthorized DataWorks writes
```

Any unchecked item means the feature remains incomplete.

- [ ] **Step 11: Commit synchronized documentation**

```powershell
git add README.md docs/product/conversational-dialog-design.md docs/superpowers/specs/2026-07-18-strong-continuous-dialogue-design.md
git commit -m "docs(dialogue): document verified continuous conversation"
```

Do not commit generated logs containing real user text or environment details.

---

## Plan Self-Review

- Spec coverage: Tasks 1–6 cover semantic continuity, mixed cards, persistence, restart recovery, stale interactions, and frontend state. Tasks 7–10 cover correlated logs, queryability, eight journeys, 50 turns, report artifacts, and completion gates.
- Type consistency: `DialogueAction`, `ResolvedTurn`, `ConversationMeta`, `InteractionAnswer`, `state_version`, `conversation_id`, `turn_id`, and `interaction_id` use the same names throughout.
- Safety: all automated end-to-end paths use a deterministic no-write provider; no task adds a DataWorks directory operation.
- Scope: existing workflows, Cookie fallback, OpenAPI clients, and Publish Gate remain intact.
- Verification: each task includes a failing-test step, implementation boundary, passing command, and commit boundary.

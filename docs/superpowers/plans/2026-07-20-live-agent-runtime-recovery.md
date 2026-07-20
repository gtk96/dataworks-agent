# Live Agent Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute this plan inline task-by-task; project instructions prohibit subagents for this run. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live 8085 table discovery distinguish authentication/outage from a genuine no-match, use eligible read-only providers, recover provably read-only poisoned conversations, and gate the behavior with real evidence.

**Architecture:** Add typed provider errors at the BFF boundary and a provider-neutral `TableDiscoveryService` used by the existing `find_table` tool. Keep free-text DataMap search on Cookie/BFF, add exact identifier checks through MaxCompute, narrowly migrate historical read-only `execution_unknown`, and persist safe tool events shared with the NDJSON stream.

**Tech Stack:** Python 3.12, FastAPI, Pydantic/dataclasses, httpx, pyodps, LangGraph SQLite, Vue 3, TypeScript, pytest, Vitest, Playwright, PowerShell.

## Global Constraints

- Never create a DataWorks folder or business-process directory.
- Do not execute a real DataWorks write during automated or live acceptance.
- Preserve destructive guards, exact node reuse, parent-directory evidence, and Publish Gate.
- `table_not_found` is legal only after at least one eligible authenticated provider completes successfully.
- Read-only failures must never produce `execution_unknown`.
- Do not broaden AK/SK permissions or claim unrestricted OpenAPI free-text search.
- Do not log Cookie, CSRF, AK/SK, authorization headers, sensitive SQL, or raw prompts.
- Full gate: Ruff, backend integration, frontend unit, frontend build, eight browser journeys, 50-turn verifier, and live read-only evidence.

---

### Task 1: Typed BFF Authentication and Provider Errors

**Files:**
- Create: `dataworks_agent/api_clients/provider_errors.py`
- Modify: `dataworks_agent/api_clients/bff_client.py:867-948`
- Test: `tests/integration/test_bff_search_errors.py`

**Interfaces:**
- Produces `ProviderError`, `ProviderAuthenticationError`, and `ProviderUnavailableError` with safe `code`, `reason`, and `provider` fields.
- `DataWorksClient.search_tables(keyword, page_size=50)` still returns `list[dict]` on success and raises a typed error otherwise.

- [x] **Step 1: Add failing business-code and empty-Cookie tests**

```python
@pytest.mark.asyncio
async def test_search_tables_raises_auth_error_for_http_200_business_403001():
    client = DataWorksClient()
    client._get = AsyncMock(return_value={"code": 403001, "reason": "USER_NOT_LOGGED_IN"})
    with pytest.raises(ProviderAuthenticationError) as caught:
        await client.search_tables("订单")
    assert caught.value.code == "cookie_auth_required"

@pytest.mark.asyncio
async def test_empty_decrypted_cookie_stops_before_http(monkeypatch):
    client = DataWorksClient()
    http = AsyncMock()
    client._http = http
    monkeypatch.setattr("dataworks_agent.api_clients.bff_client.decrypt_cookie", lambda: "")
    with pytest.raises(ProviderAuthenticationError) as caught:
        await client._get("dma/searchTables", {"keyword": "订单"})
    assert caught.value.code == "cookie_decrypt_failed"
    http.get.assert_not_awaited()
```

- [x] **Step 2: Run tests and confirm current silent-empty behavior fails**

Run: `uv run python -m pytest tests/integration/test_bff_search_errors.py -q --tb=short`

Expected: typed error imports fail or `search_tables()` returns `[]`.

- [x] **Step 3: Implement typed errors and fail-fast auth loading**

`_refresh_cookie()` raises `ProviderAuthenticationError("cookie_decrypt_failed", ...)` for an empty decrypted Cookie. `_refresh_csrf()` re-raises typed provider errors instead of swallowing them. `search_tables()` maps `403001` to `cookie_auth_required` and other non-200 business codes to `ProviderUnavailableError`.

- [x] **Step 4: Verify focused tests**

Run: `uv run python -m pytest tests/integration/test_bff_search_errors.py tests/integration/test_data_integration_api.py -q --tb=short`

- [x] **Step 5: Commit Task 1**

```powershell
git add dataworks_agent/api_clients/provider_errors.py dataworks_agent/api_clients/bff_client.py tests/integration/test_bff_search_errors.py
git commit -m "fix(bff): preserve table-search authentication failures"
```

### Task 2: Provider-Neutral Read-Only Table Discovery

**Files:**
- Create: `dataworks_agent/agent/table_discovery_service.py`
- Modify: `dataworks_agent/agent/context/metadata_provider.py:148-220`
- Modify: `dataworks_agent/agent/tools/table_discovery.py`
- Modify: `dataworks_agent/agent/core.py:109-122`
- Test: `tests/integration/test_agent_run_tools.py`

**Interfaces:**
- Produces `DiscoveryStatus` and `DiscoveryResult`.
- Produces `TableDiscoveryService.search(keyword: str, message: str) -> DiscoveryResult`.
- `TableDiscoveryTool` maps `FOUND`, `NOT_FOUND`, `AUTH_REQUIRED`, and `UNAVAILABLE` to distinct conversational responses.

- [ ] **Step 1: Add failing router tests**

```python
@pytest.mark.asyncio
async def test_bare_identifier_uses_maxcompute_exact_match_before_bff():
    service = TableDiscoveryService(
        metadata_provider=AsyncMock(),
        maxcompute=AsyncMock(),
        projects=["giikin_dev", "giikin"],
    )
    service.maxcompute.table_exists.side_effect = [True, False]
    result = await service.search("dwd_order_info", "dwd_order_info")
    assert result.status is DiscoveryStatus.FOUND
    assert result.candidates[0]["full_name"] == "giikin_dev.dwd_order_info"
    service.metadata_provider.search_table.assert_not_awaited()

@pytest.mark.asyncio
async def test_chinese_search_preserves_auth_required():
    provider = AsyncMock()
    provider.search_table.side_effect = ProviderAuthenticationError(
        "cookie_auth_required", "USER_NOT_LOGGED_IN", provider="cookie_bff"
    )
    result = await TableDiscoveryService(metadata_provider=provider).search("订单域", "订单域")
    assert result.status is DiscoveryStatus.AUTH_REQUIRED
```

- [ ] **Step 2: Run tests and confirm missing service**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py -q --tb=short`

- [ ] **Step 3: Implement minimal provider router**

Exact bare identifiers check configured MaxCompute projects. Chinese/descriptive search remains on `MetadataProvider`; typed BFF errors are preserved. OpenAPI/MCP are not used as unrestricted search substitutes unless an exact, verified contract exists.

- [ ] **Step 4: Map outcomes to truthful dialogue**

Missing keyword and authenticated no-match produce successful `waiting_user` interactions. Auth failures produce `table_search_auth_required`; outages produce `table_search_unavailable`; both are recoverable and never uncertain writes.

- [ ] **Step 5: Verify tool and coordinator tests**

Run: `uv run python -m pytest tests/integration/test_agent_run_tools.py tests/integration/test_agent_run_coordinator.py tests/integration/test_agent_runtime_journeys.py -q --tb=short`

- [ ] **Step 6: Commit Task 2**

```powershell
git add dataworks_agent/agent/table_discovery_service.py dataworks_agent/agent/context/metadata_provider.py dataworks_agent/agent/tools/table_discovery.py dataworks_agent/agent/core.py tests/integration/test_agent_run_tools.py
git commit -m "fix(agent): route table discovery by provider outcome"
```

### Task 3: Narrow Recovery for Historical Read-Only Poison States

**Files:**
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/agent/conversation_graph.py`
- Test: `tests/integration/test_agent_interaction.py`

**Interfaces:**
- Produces `ChatAgent._recover_read_only_unknown(conversation_id, context) -> dict[str, Any]`.
- Recovery consumes persisted conversation events and never clears ambiguous/write-capable uncertainty.

- [ ] **Step 1: Add failing poisoned-state tests**

```python
@pytest.mark.asyncio
async def test_legacy_find_table_llm_failure_recovers_from_execution_unknown(tmp_path):
    agent = build_agent(tmp_path)
    await seed_unknown(agent, objective="查找数据表", error="LLMError")
    seed_events(agent, action="ask_data", write_boundary_crossed=False)
    response = await agent.chat("你好", conversation_id="legacy-read")
    assert response.error != "execution_unknown"
    assert response.data["conversation"]["status"] == "recoverable_error"

@pytest.mark.asyncio
async def test_unknown_with_write_boundary_remains_blocked(tmp_path):
    agent = build_agent(tmp_path)
    await seed_unknown(agent, objective="创建 DWD 节点", error="TimeoutError")
    seed_events(agent, action="forward_modeling", write_boundary_crossed=True)
    response = await agent.chat("你好", conversation_id="legacy-write")
    assert response.error == "execution_unknown"
```

- [ ] **Step 2: Run tests and confirm read-only state remains blocked**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py -q --tb=short`

- [ ] **Step 3: Implement evidence-based recovery**

Recover only `find_table` or legacy discovery `ask_data` with provider/model/auth error evidence and no write-boundary event. Persist `recoverable_error` plus a new free-text search interaction. Do not change any state lacking sufficient evidence.

- [ ] **Step 4: Verify interaction and restart journeys**

Run: `uv run python -m pytest tests/integration/test_agent_interaction.py tests/integration/test_agent_runtime_journeys.py -q --tb=short`

- [ ] **Step 5: Commit Task 3**

```powershell
git add dataworks_agent/agent/core.py dataworks_agent/agent/conversation_graph.py tests/integration/test_agent_interaction.py
git commit -m "fix(dialogue): recover proven read-only unknown states"
```

### Task 4: Truthful Health and Persisted Tool Events

**Files:**
- Modify: `dataworks_agent/agent/capabilities.py`
- Modify: `dataworks_agent/agent/core.py`
- Modify: `dataworks_agent/agent/run_coordinator.py`
- Modify: `dataworks_agent/agent/conversation_events.py`
- Test: `tests/integration/test_agent_capabilities.py`
- Test: `tests/integration/test_chat_agent_event_chain.py`

**Interfaces:**
- BFF probe validates a non-empty CSRF token and one bounded read-only business request.
- Persisted tool events contain only tool name, declared side effect, provider, success, safe error code, and uncertainty flag.

- [ ] **Step 1: Add failing health and event tests**

Assert `403001` becomes `cookie_auth_required`, exact-name discovery remains partially available through MaxCompute, and a live bounded run persists ordered `tool.started/tool.completed` events without arguments or raw messages.

- [ ] **Step 2: Run focused tests and confirm missing semantics**

Run: `uv run python -m pytest tests/integration/test_agent_capabilities.py tests/integration/test_chat_agent_event_chain.py -q --tb=short`

- [ ] **Step 3: Implement business-aware health**

Replace unconditional `_probe_bff()` success with token/business validation. Report stable safe codes and represent exact-name versus free-text search availability without claiming unrestricted search.

- [ ] **Step 4: Tee NDJSON events into the conversation recorder**

Persist only safe event fields. Add discovery error codes to the recorder allowlist so `table_search_auth_required`, `table_search_unavailable`, and `table_not_found` are not collapsed to `response_error`.

- [ ] **Step 5: Verify health and event tests**

Run: `uv run python -m pytest tests/integration/test_agent_capabilities.py tests/integration/test_chat_agent_event_chain.py tests/integration/test_conversation_events.py -q --tb=short`

- [ ] **Step 6: Commit Task 4**

```powershell
git add dataworks_agent/agent/capabilities.py dataworks_agent/agent/core.py dataworks_agent/agent/run_coordinator.py dataworks_agent/agent/conversation_events.py tests/integration/test_agent_capabilities.py tests/integration/test_chat_agent_event_chain.py
git commit -m "fix(observability): expose live discovery failures"
```

### Task 5: Frontend Recovery Semantics and Browser Coverage

**Files:**
- Modify: `frontend/src/pages/SmartChatPage.vue`
- Modify: `frontend/e2e/agent-runtime.spec.ts`
- Modify: `tests/e2e/dialogue_server.py`
- Modify: `tests/support/agent_runtime.py`
- Test: `frontend/src/__tests__/conversationLifecycle.spec.ts`

**Interfaces:**
- UI labels `waiting_user`, `recoverable_error`, and `execution_unknown` distinctly.
- Acceptance server can deterministically return auth-required, unavailable, no-match, and found outcomes.

- [ ] **Step 1: Add failing frontend mode and browser assertions**

Assert the page renders `等待补充`, `依赖待恢复`, and `执行结果待确认`; auth-required copy must not contain `没有找到`.

- [ ] **Step 2: Run frontend tests and confirm missing labels**

Run from `frontend`: `npm run test:unit`

- [ ] **Step 3: Implement labels and deterministic provider modes**

Map backend modes to Chinese UI labels and extend the no-write acceptance provider without adding production-only switches.

- [ ] **Step 4: Add browser recovery journeys**

Extend the existing eight journeys without increasing the count: dependency degradation must distinguish authentication from no-match; restart journey must cover proven read-only poison recovery.

- [ ] **Step 5: Verify frontend and browser tests**

Run from `frontend`: `npm run test:unit`, `npm run build`, then `npm run test:e2e`.

- [ ] **Step 6: Commit Task 5**

```powershell
git add frontend/src/pages/SmartChatPage.vue frontend/src/__tests__/conversationLifecycle.spec.ts frontend/e2e/agent-runtime.spec.ts tests/e2e/dialogue_server.py tests/support/agent_runtime.py
git commit -m "fix(frontend): distinguish discovery recovery states"
```

### Task 6: Full Regression and Live 8085 Read-Only Gate

**Files:**
- Modify: `scripts/run_continuous_dialogue_acceptance.ps1`
- Create: `dataworks_agent/scripts/verify_live_table_discovery.py`
- Modify: `docs/product/conversational-dialog-design.md`
- Modify: `docs/superpowers/plans/2026-07-20-live-agent-runtime-recovery.md`

**Interfaces:**
- `verify_live_table_discovery.py --base-url http://127.0.0.1:8085 --output <dir> [--canary project.table]` exits nonzero for false no-match, write evidence, or an expected canary miss.

- [ ] **Step 1: Implement assertion-based live verifier**

Record health, transcript, run events, provider provenance, and write audit. Classify runs without a configured canary as dependency-only, never full live success.

- [ ] **Step 2: Run focused backend verification**

Run: `uv run python -m pytest tests/integration/test_bff_search_errors.py tests/integration/test_agent_run_tools.py tests/integration/test_agent_capabilities.py tests/integration/test_agent_interaction.py tests/integration/test_chat_agent_event_chain.py -q --tb=short`

- [ ] **Step 3: Run all regression gates**

Run: `uv run ruff check .`

Run: `uv run python -m pytest tests/integration/ -q --tb=short`

Run from `frontend`: `npm run test:unit`, `npm run build`, and `npm run test:e2e`.

Run: `uv run python -m dataworks_agent.scripts.verify_agent_runtime --output reports/continuous-dialogue/backend-live-recovery`

- [ ] **Step 4: Restart current branch on 8085**

Stop only PID 80420 if still bound to 8085, start the current worktree build, and wait for `/api/health` without performing a write.

- [ ] **Step 5: Run live read-only verifier and inspect logs**

Run: `uv run python -m dataworks_agent.scripts.verify_live_table_discovery --base-url http://127.0.0.1:8085 --output reports/continuous-dialogue/<run-id>`.

Assert no `create_node`, `update_node`, `delete_node`, `deploy`, `publish`, `execute_ddl`, write boundary, or false `execution_unknown` event.

- [ ] **Step 6: Synchronize documentation and completion evidence**

Document exact dependency health, whether a real canary succeeded, test counts, and the valid report path. Do not call dependency-only validation a full live pass.

- [ ] **Step 7: Commit Task 6**

```powershell
git add scripts/run_continuous_dialogue_acceptance.ps1 dataworks_agent/scripts/verify_live_table_discovery.py docs/product/conversational-dialog-design.md docs/superpowers/plans/2026-07-20-live-agent-runtime-recovery.md
git commit -m "test(agent): gate live discovery recovery"
```

## Plan Self-Review

- Spec coverage: Tasks 1-6 cover typed BFF errors, provider routing, read-only poison recovery, health, persisted tool events, UI semantics, deterministic regression, and live read-only acceptance.
- Safety: every new external call is metadata-only; no task authorizes DataWorks directory or write operations.
- Type consistency: `ProviderAuthenticationError`, `ProviderUnavailableError`, `DiscoveryStatus`, `DiscoveryResult`, and `TableDiscoveryService.search()` are defined once and consumed consistently.
- Scope: unrestricted LLM autonomy and a broad tool catalog remain explicit non-goals; this plan repairs the observed live vertical slice without claiming more.
- Placeholder scan: clean; every implementation and verification step names concrete files, behavior, commands, and expected evidence.

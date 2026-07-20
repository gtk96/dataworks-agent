# Live Agent Runtime Recovery Design

**Date:** 2026-07-20  
**Branch:** `feat/strong-continuous-dialogue`  
**Status:** Approved direction; implementation pending

## 1. Problem Statement

The page runtime can preserve a deterministic conversation, but live table discovery currently reports authentication failures as empty search results. The latest 8085 session proved this chain:

```text
COOKIE_ENCRYPTION_KEY mismatch
→ decrypt_cookie() returns an empty string
→ dma/searchTables returns HTTP 200 with business code 403001 USER_NOT_LOGGED_IN
→ DataWorksClient.search_tables() converts the response to []
→ MetadataProvider treats [] as no candidates
→ find_table tells the user that no reliable table exists
```

The runtime also has four related gaps:

1. `find_table` is hard-wired to Cookie/BFF even when MaxCompute, OpenAPI, or the official MCP is online.
2. Historical read-only table-search failures can remain persisted as `execution_unknown`, preventing ordinary conversation after restart.
3. Expected clarification and recoverable dependency failures are recorded as generic `ERROR/response_error` events.
4. Deterministic acceptance providers prove dialogue mechanics but do not prove that live 8085 distinguishes a real no-match from an unavailable provider.

## 2. Goals

1. Never report `table_not_found` when every eligible provider failed or was unauthenticated.
2. Route read-only table discovery across the available capability matrix without performing any DataWorks write.
3. Recover only historical `execution_unknown` states that can be proven to originate from a read-only search path that never crossed a write boundary.
4. Make capability health and conversation logs expose actionable, non-secret failure codes.
5. Add a live 8085 read-only acceptance gate that verifies provider failure semantics and at least one known metadata success path when the environment supplies a canary.
6. Preserve the existing write guards, parent-directory requirements, exact node reuse, and Publish Gate.

## 3. Non-Goals

- Do not create, update, delete, deploy, or publish a real DataWorks node.
- Do not create a DataWorks folder or business-process directory.
- Do not broaden AK/SK permissions.
- Do not remove the long-lived Cookie/BFF fallback.
- Do not replace the existing modeling, diagnosis, query, or Publish Gate implementations.
- Do not claim general Codex-like autonomy until an actual LLM decision provider and a broader typed-tool catalog are separately verified.

## 4. Selected Architecture

### 4.1 Typed discovery outcomes

Introduce a provider-neutral result contract for read-only discovery:

```python
class DiscoveryStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class DiscoveryResult:
    status: DiscoveryStatus
    candidates: list[dict[str, Any]]
    provider: str
    error_code: str = ""
```

`NOT_FOUND` is valid only when at least one eligible provider completed an authenticated query and returned no match. Authentication or transport failures remain distinct outcomes.

### 4.2 BFF business-error boundary

`DataWorksClient.search_tables()` must validate both HTTP status and BFF business code. Known authentication codes, including `403001`, raise a typed read-only authentication error and retain only a safe code/reason. Other non-200 business codes raise a typed provider error. They must never become an empty list.

Cookie loading fails fast when encrypted data cannot be decrypted. The request path must not repeatedly derive the same failed key or send an empty Cookie. CDP refresh remains an explicit recovery attempt, not an implicit claim that the search returned no rows.

### 4.3 Read-only provider router

`TableDiscoveryTool` depends on a `TableDiscoveryService`, not directly on `MetadataProvider`.

Routing rules:

1. A fully qualified `project.table` uses exact MaxCompute/OpenAPI metadata inspection first.
2. A bare identifier such as `gk_order_info` performs exact existence checks in the configured dev and permitted production projects, then uses authenticated BFF fuzzy search if available.
3. Chinese or descriptive keywords use authenticated BFF/DataMap search first because AK/SK does not provide unrestricted free-text metadata search under the current permission model.
4. Official MCP may be used only for a declared, read-only table-list or table-detail capability whose response contract is verified.
5. If a provider is offline, continue only to a semantically equivalent eligible provider. Do not pretend that exact existence checks replace Chinese comment search.
6. Merge candidates by normalized full identifier and retain provider provenance.

The service returns `AUTH_REQUIRED` or `UNAVAILABLE` when no eligible provider completed successfully. The page then offers actionable recovery or a new goal, without marking the operation `execution_unknown`.

### 4.4 Historical state recovery

Automatic recovery is deliberately narrow. On load, an `execution_unknown` state may be converted to `recoverable_error` only when persisted evidence proves all of the following:

- the originating action was `find_table` or the legacy read-only `ask_data` discovery entry;
- no tool or workflow recorded `write_boundary_crossed=true`;
- no node, DDL, deploy, publish, delete, or other write-capable operation was started;
- the stored error is a model/provider/authentication failure rather than an unknown write result.

If evidence is missing or contradictory, preserve `execution_unknown`. Manual `reset` and `new task` remain available.

### 4.5 Capability health

The BFF probe must validate a usable CSRF token and a bounded read-only business request. It reports stable codes such as:

- `cookie_decrypt_failed`
- `cookie_auth_required`
- `cdp_unavailable`
- `bff_timeout`

`table_search.online` reflects the discovery router, not BFF alone: exact-name discovery can remain partially online through MaxCompute while free-text DataMap search is unavailable. The API exposes per-mode capability details without secrets.

### 4.6 Event and UI semantics

Persist `run.started`, `decision.*`, `tool.started`, `tool.completed`, `state.persisted`, and `response.completed` with safe tool/error metadata so the audit log matches the NDJSON stream.

Clarification is a successful conversational transition with `task_status=waiting_user`. Provider authentication and availability failures use `recoverable_error`, but are not collapsed to generic `response_error`. The frontend maps all supported modes to user-facing Chinese labels and presents authentication recovery separately from a genuine no-match.

## 5. Error Matrix

| Condition | Tool result | Conversation status | User message |
|---|---|---|---|
| Missing keyword | clarification | `waiting_user` | Ask for a keyword |
| Authenticated provider returns zero | `table_not_found` | `waiting_user` | No match; refine keyword |
| Cookie decrypt/BFF login failure, no equivalent provider | `table_search_auth_required` | `recoverable_error` | Explain authentication is unavailable |
| Timeout/provider outage | `table_search_unavailable` | `recoverable_error` | Explain dependency outage and retry options |
| Exact table found through MaxCompute | success | `active` | Present exact table and next actions |
| Write-capable tool crossed boundary, result unknown | `execution_unknown` | `execution_unknown` | Block duplicate writes |

## 6. Test Strategy

### 6.1 Unit and integration

- BFF HTTP 200 plus `code=403001` raises typed authentication failure.
- Empty authenticated BFF results remain `NOT_FOUND`.
- Cookie decrypt failure does not send a BFF search request with an empty Cookie.
- Exact bare identifiers use MaxCompute before BFF and preserve project-qualified identifiers.
- Chinese keyword search reports `AUTH_REQUIRED` when BFF is unauthenticated.
- Read-only failures never produce `execution_unknown`.
- Proven historical read-only poison state migrates; ambiguous/write-capable state does not.
- Capability responses distinguish exact-name and free-text discovery availability.
- Persisted events include tool name, provider, safe error code, and side effect.
- Clarification is not logged as a generic error.

### 6.2 Browser acceptance

Keep deterministic journeys for repeatable state/concurrency coverage, and add explicit browser assertions for:

- auth-required versus no-match copy;
- Chinese labels for `waiting_user` and `recoverable_error`;
- recovery to a new goal after provider failure;
- restored historical read-only poisoned state.

### 6.3 Live 8085 read-only gate

The gate performs no writes and records provider provenance:

1. force-refresh `/agent/capabilities`;
2. submit a configured exact-table canary when available;
3. submit a free-text keyword and assert that authentication failure is not reported as no-match;
4. verify greeting, explanation, reset, and a new goal remain usable;
5. scan network and backend events for forbidden write endpoints, write boundaries, and `execution_unknown`;
6. fail when the environment has no success canary unless the report explicitly classifies the run as dependency-only validation rather than full live acceptance.

## 7. Safety

- All new provider calls are metadata reads.
- Automated tests use fakes or read-only probes.
- No test calls create/update/delete/deploy/publish/DDL endpoints.
- Existing DataWorks directory and node guards remain unchanged.
- Logs store safe error codes and provider names, never Cookie, CSRF, AK/SK, authorization headers, or sensitive SQL.

## 8. Completion Criteria

The repair is complete only when:

- focused regression tests pass;
- full backend integration, Ruff, frontend unit, frontend build, and eight browser journeys pass;
- BFF `403001` is visibly classified as authentication failure;
- a poisoned read-only conversation becomes usable without weakening real write uncertainty;
- live 8085 produces no false `table_not_found` for unavailable providers;
- the report identifies whether a real metadata success canary passed;
- zero DataWorks writes and zero DataWorks directory creations are recorded.


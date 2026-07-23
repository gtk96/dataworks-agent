# DataWorks Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork the active OpenCode codebase into a multi-user DataWorks-specialized Web agent with isolated per-user OpenCode workers, encrypted local credentials, DataWorks OpenAPI/PyODPS/MCP tools, Skill/RAG support, and staging-backed integration acceptance.

**Architecture:** Keep `anomalyco/opencode`’s Bun/TypeScript/Effect runtime, SessionV2, ToolRegistry, generated SDK, and SolidJS app. Add a same-origin DataWorks control plane that authenticates users and proxies each user to an isolated OpenCode worker; DataWorks tools run as an OpenCode plugin and call the control plane through a short-lived internal token. Use the official DataWorks TypeScript SDK for OpenAPI operations and a supervised PyODPS JSON-RPC sidecar for MaxCompute SQL.

**Tech Stack:** OpenCode baseline `anomalyco/opencode@cd46f22d513d60b7a9bdca1111d25c50d2398355` (MIT), Bun 1.3.14, TypeScript 5.8.2, Effect 4 beta, SolidJS 1.9.10, Vite 7.1.4, Tailwind CSS 4.1.11, SQLite/Drizzle, `@alicloud/dataworks-public20200518@10.0.0`, PyODPS 0.13.0 managed by uv, `@napi-rs/keyring@1.3.0`, `@node-rs/argon2@2.0.2`, `@lancedb/lancedb@0.31.0`, Playwright 1.59.1.

## Global Constraints

- Upstream baseline is exactly `anomalyco/opencode@cd46f22d513d60b7a9bdca1111d25c50d2398355`; preserve its MIT `LICENSE` and notices.
- Add `upstream=https://github.com/anomalyco/opencode.git`; all recurring syncs come from `upstream/dev` through an `upstream-sync` PR.
- Use Bun 1.3.14 and run package tests/typechecks from their package directory; never run the guarded root test command.
- Keep the fork delta small: prefer new workspace packages, external plugins, control-plane API groups, and new SolidJS pages; changes to OpenCode core registration points require two reviewers.
- Branch names are at most three hyphen-separated words with no `/`; merge through squash merge so `main` keeps one Conventional Commit per PR.
- Integration tests are primary. Add unit tests only for parsing, cryptography, permission/path policy, and other pure invariants.
- Every feature must work with `DATAWORKS_AGENT_DRY_RUN=1` using sanitized fixtures; staging tests must use dedicated least-privilege credentials.
- Never expose Aliyun credentials, LLM API keys, MCP tokens, worker passwords, raw session tokens, or another user’s file/knowledge/session data to browser state, logs, fixtures, or git.
- DataWorks write tools are disabled by default. Enabling them still requires an OpenCode permission prompt, a user-entered reason, an audited one-time execution ticket, and server-side reauthorization.
- OpenCode’s Project/Workspace names retain their VCS meaning. Alibaba credentials live under the distinct `DataConnection` domain.
- Private data root is resolved by the app (`%APPDATA%\dataworks-agent` on Windows; XDG data/config paths on Linux/macOS); do not hard-code `~/.dataworks_agent` as a literal platform path.
- Multi-user or production workers must run in an OCI sandbox. Native workers are permitted only for loopback-bound, single-user development and must refuse production or a second user.
- Containers run non-root with read-only rootfs, dropped capabilities, no-new-privileges, default seccomp, resource limits, no host network, and mounts limited to the user root plus administrator-approved project roots.
- Worker HTTP(S) egress passes through a control-plane allowlist proxy; block loopback, link-local, RFC1918, and cloud metadata destinations except the authenticated internal control-plane route.
- “Local protection” covers at-rest and tenant isolation, not automatic consent to remote inference. Knowledge/project sources default to `local_only` or `prompt_only` and require audited provider-specific approval before remote transmission.
- The product uses OpenCode’s SolidJS UI. Apply new-api-inspired visual tokens only; do not copy QuantumNous/new-api code, branding, attribution, or protected identifiers.
- User-facing copy must be present in at least `packages/app/src/i18n/en.ts` and `packages/app/src/i18n/zh.ts`.

---

## File Structure Map

### Upstream-owned files imported unchanged at M0

- `packages/opencode/` — OpenCode agent runtime, server, tools, provider handling, CLI.
- `packages/core/` — Effect services, SQLite/Drizzle schema, SessionV2 and common abstractions.
- `packages/server/` — reusable server middleware/contracts.
- `packages/protocol/`, `packages/client/`, `packages/sdk/` — generated public API and clients.
- `packages/app/`, `packages/ui/` — SolidJS Web UI and shared components.
- All other upstream workspaces remain available unless a later measured build reduction removes them.

### DataWorks Agent additions

- `UPSTREAM.md` — pinned baseline, remote topology, monthly sync procedure, accepted conflict policy.
- `packages/dataworks-control/` — multi-user auth, control-plane database tables, worker supervisor/reverse proxy, DataWorks/RAG APIs.
- `packages/dataworks-core/` — shared Effect schemas, IDs, redaction contracts, DataConnection/audit/knowledge domain types.
- `packages/dataworks-plugin/` — OpenCode plugin exposing `dw_*` tools and RAG system-context hooks.
- `sidecars/pyodps/` — uv-managed Python process implementing newline-delimited JSON-RPC over stdio.
- `packages/app/src/pages/dataworks/` — DataWorks connection, explorer, jobs, knowledge, audit pages.
- `packages/app/src/context/dataworks.tsx` — typed control-plane client/session context.
- `tests/integration/` — cross-package dry-run and staging suites.
- `.github/workflows/` — lint/typecheck/dry-run/staging/web-E2E/upstream-sync gates.

### Deliberate boundaries

- `packages/dataworks-control` owns users, browser sessions, encrypted DataWorks/LLM/MCP secrets, worker lifecycle, the streaming LLM credential gateway, knowledge data, and auditing.
- OpenCode workers own only that user’s code projects, OpenCode sessions, model selections, permissions, and non-secret Provider routing configuration. They never store real LLM/DataWorks/MCP credentials in multi-user mode.
- `packages/dataworks-plugin` never reads `secrets.dat`; it calls authenticated control-plane internal APIs.
- PyODPS never receives browser/user auth tokens; the control plane passes one request’s resolved connection credentials over the sidecar’s private stdio.

---

## M0 — Fork Baseline and Governance

### Task 1: Import the pinned OpenCode fork baseline

**Depends on:** None

**Estimated review size:** 1 PR; repository import plus governance metadata

**Files:**
- Import: all tracked files from `anomalyco/opencode@cd46f22d513d60b7a9bdca1111d25c50d2398355`
- Preserve/merge: `README.md`, `CONTRIBUTING.md`, `.gitignore`, `docs/superpowers/**`
- Create: `UPSTREAM.md`
- Create: `NOTICE-DATAWORKS-AGENT.md`
- Modify: `package.json`
- Modify: `.env.example`
- Create: `upstream-baseline.json`
- Create: `scripts/verify-upstream-baseline.ts`
- Test: `scripts/verify-upstream-baseline.test.ts`

**Interfaces:**
- Consumes: upstream commit `cd46f22d513d60b7a9bdca1111d25c50d2398355`.
- Produces: root script `bun run verify:upstream`; `UPSTREAM.md` declaring `origin` and `upstream`; monorepo ready for additional workspaces.

- [ ] **Step 1: Create a safety tag for the approved design-only state**

Run:

```bash
git tag design-v0.1 d5fcb09
```

Expected: `git show-ref --tags design-v0.1` resolves to `d5fcb09`.

- [ ] **Step 2: Add the upstream remote and fetch the exact baseline**

Run:

```bash
git remote add upstream https://github.com/anomalyco/opencode.git
git fetch upstream cd46f22d513d60b7a9bdca1111d25c50d2398355
git remote -v
```

Expected: `upstream` has fetch/push URLs and `FETCH_HEAD` resolves to the pinned SHA.

- [ ] **Step 3: Merge the upstream history without losing local design commits**

Run on a new branch:

```bash
git switch -c upstream-base
git merge --allow-unrelated-histories --no-commit cd46f22d513d60b7a9bdca1111d25c50d2398355
```

Resolve the expected root-document conflicts by retaining the DataWorks Agent versions while preserving all upstream code, license, notices, AGENTS instructions, workspaces, lockfile, and GitHub metadata:

```bash
git checkout --ours -- README.md CONTRIBUTING.md .gitignore
git add README.md CONTRIBUTING.md .gitignore
git status --short
```

If `git status` shows any additional unmerged path, inspect both sides and resolve it explicitly; do not use a repository-wide `--ours` or `--theirs`. The merge is not ready until `git diff --name-only --diff-filter=U` prints nothing.

Expected: `packages/opencode/package.json` reports version `1.18.3`; local design docs remain under `docs/superpowers/`; upstream `LICENSE`, `NOTICE`, and `AGENTS.md` are present.

- [ ] **Step 4: Write the baseline verifier test first**

Create `scripts/verify-upstream-baseline.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import baseline from "../upstream-baseline.json"

describe("upstream baseline", () => {
  test("pins the approved active OpenCode commit", () => {
    expect(baseline).toEqual({
      repository: "https://github.com/anomalyco/opencode.git",
      branch: "dev",
      commit: "cd46f22d513d60b7a9bdca1111d25c50d2398355",
      license: "MIT",
    })
  })
})
```

Create `upstream-baseline.json` with exactly the expected object.

- [ ] **Step 5: Run the baseline test**

Run:

```bash
bun test scripts/verify-upstream-baseline.test.ts
```

Expected: PASS, 1 test.

- [ ] **Step 6: Add a verifier script and governance docs**

Create `scripts/verify-upstream-baseline.ts`:

```ts
import baseline from "../upstream-baseline.json"

const result = Bun.spawnSync(["git", "cat-file", "-e", `${baseline.commit}^{commit}`])
if (result.exitCode !== 0) {
  console.error(`Missing pinned upstream commit ${baseline.commit}`)
  process.exit(1)
}
console.log(`${baseline.repository}@${baseline.commit}`)
```

Add to root `package.json` scripts:

```json
"verify:upstream": "bun scripts/verify-upstream-baseline.ts"
```

Write `UPSTREAM.md` with these exact policies:

```markdown
# Upstream Policy

- Upstream: https://github.com/anomalyco/opencode.git
- Tracked branch: dev
- Initial baseline: cd46f22d513d60b7a9bdca1111d25c50d2398355
- Sync branch: upstream-sync
- Sync cadence: monthly and before every minor release
- Merge gate: package typechecks, OpenCode HttpApi exercise, DataWorks dry-run integration, Playwright critical path
- Core conflict policy: prefer upstream behavior; keep DataWorks changes in new packages/API groups/pages; document every unavoidable core patch in this file.
```

`NOTICE-DATAWORKS-AGENT.md` must state that the product is a derivative of OpenCode under MIT and list separate third-party licenses; it must not imply endorsement.

- [ ] **Step 7: Install the pinned workspace and run upstream smoke checks**

Run:

```bash
bun install --frozen-lockfile
bun run verify:upstream
bun run --cwd packages/core typecheck
bun run --cwd packages/opencode typecheck
bun run --cwd packages/app typecheck
```

Expected: the verifier prints the pinned SHA; all three typechecks exit 0.

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "chore: import pinned opencode upstream"
```

**Dry-run acceptance:** `bun dev serve --port 4096` starts and `GET /global/health` returns the upstream health payload without requiring DataWorks credentials.

---

### Task 2: Establish CI, PR governance, and dry-run contracts

**Depends on:** Task 1

**Estimated review size:** 1 PR; CI/config only

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/CODEOWNERS`
- Create: `.github/workflows/verify.yml`
- Create: `.github/workflows/staging.yml`
- Create: `.github/workflows/upstream-sync.yml`
- Create: `packages/dataworks-core/package.json`
- Create: `packages/dataworks-core/tsconfig.json`
- Create: `packages/dataworks-core/src/config.ts`
- Test: `packages/dataworks-core/test/config.test.ts`
- Modify: `package.json`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- Produces: `DataWorksConfig.Info`, `DataWorksConfig.load(env)`, and CI jobs `upstream`, `dataworks-dry-run`, `web-e2e`, `staging`.

- [ ] **Step 1: Write the dry-run config test**

Create `packages/dataworks-core/test/config.test.ts`:

```ts
import { describe, expect, test } from "bun:test"
import { DataWorksConfig } from "../src/config"

describe("DataWorksConfig", () => {
  test("defaults to safe local dry-run", () => {
    expect(DataWorksConfig.load({})).toEqual({
      dryRun: true,
      host: "127.0.0.1",
      port: 8084,
      publicRegistration: false,
      workerIdleSeconds: 900,
    })
  })

  test("rejects disabling dry-run without an environment name", () => {
    expect(() => DataWorksConfig.load({ DATAWORKS_AGENT_DRY_RUN: "0" })).toThrow("DATAWORKS_AGENT_ENV")
  })
})
```

- [ ] **Step 2: Run the test and observe failure**

Run:

```bash
bun test packages/dataworks-core/test/config.test.ts
```

Expected: FAIL because `../src/config` does not exist.

- [ ] **Step 3: Implement the minimal config boundary**

Create `packages/dataworks-core/src/config.ts`:

```ts
import { Schema } from "effect"

const Info = Schema.Struct({
  dryRun: Schema.Boolean,
  host: Schema.String,
  port: Schema.Number,
  publicRegistration: Schema.Boolean,
  workerIdleSeconds: Schema.Number,
})

function bool(value: string | undefined, fallback: boolean) {
  if (value === undefined) return fallback
  return value === "1" || value.toLowerCase() === "true"
}

export function load(env: Record<string, string | undefined>): typeof Info.Type {
  const dryRun = bool(env.DATAWORKS_AGENT_DRY_RUN, true)
  if (!dryRun && !env.DATAWORKS_AGENT_ENV) throw new Error("DATAWORKS_AGENT_ENV is required when dry-run is disabled")
  return {
    dryRun,
    host: env.HOST ?? "127.0.0.1",
    port: Number(env.PORT ?? 8084),
    publicRegistration: bool(env.DATAWORKS_AGENT_PUBLIC_REGISTRATION, false),
    workerIdleSeconds: Number(env.DATAWORKS_AGENT_WORKER_IDLE_SECONDS ?? 900),
  }
}

export const DataWorksConfig = { Info, load }
```

- [ ] **Step 4: Run test and typecheck**

Run:

```bash
bun test packages/dataworks-core/test/config.test.ts
bun run --cwd packages/dataworks-core typecheck
```

Expected: both PASS.

- [ ] **Step 5: Add governance files**

`.github/PULL_REQUEST_TEMPLATE.md` must contain checkboxes for issue, scope, dry-run command/output, staging evidence, web screenshot/video, secret scan, rollback, and upstream conflict notes. Resolve the current GitHub account with `gh api user --jq '.login'`; for the current authorized account this is `gtk96`. Until organization teams are created, `.github/CODEOWNERS` must use that real reviewer:

```text
/packages/opencode/src/tool/ @gtk96
/packages/opencode/src/permission/ @gtk96
/packages/opencode/src/plugin/ @gtk96
/packages/dataworks-control/src/secret/ @gtk96
/packages/dataworks-control/src/worker/ @gtk96
```

Before enabling branch protection, run `gh repo view --json owner,url` and verify `@gtk96` has write access. Repository creation/remote configuration is an explicit external gate: Task 2 remains in progress until that command succeeds against the target repository and CODEOWNERS is recognized by GitHub.

- [ ] **Step 6: Add CI workflows**

`verify.yml` runs on every PR:

```yaml
- bun install --frozen-lockfile
- bun run verify:upstream
- bun run lint
- bun run --cwd packages/core typecheck
- bun run --cwd packages/opencode typecheck
- bun run --cwd packages/app typecheck
- bun test packages/dataworks-core/test
- DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run
```

`staging.yml` runs only on protected `main`, `release-*`, or manual dispatch, targets GitHub Environment `dataworks-staging`, and requires `ALIYUN_ACCESS_KEY_ID`, `ALIYUN_ACCESS_KEY_SECRET`, `ALIYUN_DATAWORKS_REGION`, `ALIYUN_DATAWORKS_PROJECT_ID`, `ODPS_PROJECT`, `ODPS_ENDPOINT`. It must never run on fork PRs.

`upstream-sync.yml` fetches `upstream/dev`, opens/updates an `upstream-sync` PR, and runs the same full verification suite; it never auto-merges.

- [ ] **Step 7: Validate workflows locally**

Run:

```bash
bun run lint
DATAWORKS_AGENT_DRY_RUN=1 bun test packages/dataworks-core/test
```

Expected: exit 0. Validate YAML with GitHub’s workflow parser when pushed; the first PR must show `verify` jobs as required checks.

- [ ] **Step 8: Commit**

```bash
git add .github package.json packages/dataworks-core CONTRIBUTING.md
git commit -m "chore(ci): establish fork verification gates"
```

**Dry-run acceptance:** PR verification completes without cloud credentials and reports no secret-dependent skipped test as a pass.

---

## M1 — Authentication, Data Connections, and Worker Isolation

### Task 3: Add the control-plane database schema and local authentication

**Depends on:** Task 2

**Estimated review size:** 1 PR; auth schema/API/browser session

**Files:**
- Create: `packages/dataworks-control/package.json`
- Create: `packages/dataworks-control/tsconfig.json`
- Create: `packages/dataworks-control/src/schema.ts`
- Create: `packages/dataworks-control/src/database.ts`
- Create: `packages/dataworks-control/src/migration.ts`
- Create: `packages/dataworks-control/drizzle.config.ts`
- Create: `packages/dataworks-control/migration/0001_auth.sql`
- Create: `packages/dataworks-control/src/auth/password.ts`
- Create: `packages/dataworks-control/src/auth/session.ts`
- Create: `packages/dataworks-control/src/http/csrf.ts`
- Create: `packages/dataworks-control/src/http/auth-api.ts`
- Create: `packages/dataworks-control/src/http/server.ts`
- Create: `packages/dataworks-control/src/cli/create-admin.ts`
- Create: `packages/dataworks-control/test/support/server.ts`
- Create: `packages/dataworks-core/src/identity.ts`
- Test: `packages/dataworks-control/test/auth.integration.test.ts`
- Modify: `package.json`

**Interfaces:**
- Produces: `UserID`, `AuthSession.Info`, `AuthSession.authenticate(request)`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, and `dwa_session` HttpOnly Cookie.

- [ ] **Step 1: Write the full HTTP auth integration test**

Create `packages/dataworks-control/test/auth.integration.test.ts`:

```ts
import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { makeTestServer } from "./support/server"

const app = makeTestServer()

beforeAll(() => app.start())
afterAll(() => app.stop())

describe("local auth", () => {
  test("logs in, resolves current user, and revokes logout", async () => {
    await app.createUser({ email: "admin@example.test", password: "correct-horse", role: "admin" })
    const login = await fetch(`${app.url}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "admin@example.test", password: "correct-horse" }),
    })
    expect(login.status).toBe(204)
    const cookie = login.headers.get("set-cookie")!
    expect(cookie).toContain("dwa_session=")
    expect(cookie).toContain("HttpOnly")
    expect(cookie).toContain("SameSite=Lax")

    const me = await fetch(`${app.url}/api/auth/me`, { headers: { cookie } })
    expect(await me.json()).toMatchObject({ email: "admin@example.test", role: "admin" })

    const logout = await fetch(`${app.url}/api/auth/logout`, { method: "POST", headers: { cookie } })
    expect(logout.status).toBe(204)
    expect((await fetch(`${app.url}/api/auth/me`, { headers: { cookie } })).status).toBe(401)
  })
})
```

`packages/dataworks-control/test/support/server.ts` must use a temporary SQLite path and invoke the actual HTTP handlers, not mocked repositories.

- [ ] **Step 2: Run the integration test to verify failure**

Run:

```bash
bun test packages/dataworks-control/test/auth.integration.test.ts
```

Expected: FAIL because control-plane package/server do not exist.

- [ ] **Step 3: Define tables, IDs, and the independent control-plane migration chain**

In `src/schema.ts`, define Drizzle SQLite tables:

```ts
export const UserTable = sqliteTable("dwa_user", {
  id: text().$type<UserID>().primaryKey(),
  email: text().notNull().unique(),
  password_hash: text().notNull(),
  role: text({ enum: ["admin", "user"] }).notNull(),
  disabled: integer({ mode: "boolean" }).notNull().default(false),
  time_created: integer().notNull(),
  time_updated: integer().notNull(),
})

export const BrowserSessionTable = sqliteTable("dwa_browser_session", {
  token_hash: text().primaryKey(),
  user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
  time_expires: integer().notNull(),
  time_created: integer().notNull(),
})
```

Use branded Effect Schema IDs in `packages/dataworks-core/src/identity.ts`. Store these tables in a separate `<app-data>/control.sqlite`, not OpenCode’s per-user database. `migration.ts` runs ordered SQL files transactionally and records `{ id, sha256, time_completed }` in `dwa_migration`; startup fails if an already-applied migration’s checksum changes. Add package scripts `db:generate` and `db:verify`, and assert a fresh database plus upgrade from an empty v0 file both reach the expected schema.

- [ ] **Step 4: Implement password and token rules**

Use `@node-rs/argon2@2.0.2` with Argon2id and explicit parameters:

```ts
const hashOptions = {
  algorithm: Algorithm.Argon2id,
  memoryCost: 19456,
  timeCost: 2,
  parallelism: 1,
  outputLen: 32,
}
```

Generate browser tokens with `crypto.getRandomValues(new Uint8Array(32))`; return base64url to the browser and store only `sha256(token)` in SQLite. Set a 12-hour absolute expiry; delete expired rows during authentication.

- [ ] **Step 5: Implement the auth API**

- `POST /api/auth/login`: generic 401 for unknown user/wrong password/disabled user; rate-limit by IP+email (5 failures/15 minutes).
- `POST /api/auth/logout`: delete the current session hash and expire Cookie.
- `GET /api/auth/me`: return `{ id, email, role }` only.
- Cookie: `Path=/; HttpOnly; SameSite=Lax`; add `Secure` outside development.
- For every state-changing same-origin route, reject requests whose `Origin` does not exactly match configured public origin; when browsers omit `Origin`, require `Sec-Fetch-Site` to be `same-origin` or `none`. Apply the same gate before proxying state-changing `/opencode/*` requests and WebSocket upgrades. Do not enable wildcard CORS with credentials.
- `create-admin` reads password from a TTY prompt or `DWA_BOOTSTRAP_PASSWORD`; it never accepts a password command-line argument.

- [ ] **Step 6: Run auth integration and package typecheck**

Run:

```bash
bun test packages/dataworks-control/test/auth.integration.test.ts
bun run --cwd packages/dataworks-control typecheck
```

Expected: PASS; SQLite file is created only under the test temp directory.

- [ ] **Step 7: Commit**

```bash
git add packages/dataworks-control packages/dataworks-core package.json bun.lock
git commit -m "feat(auth): add local multi-user sessions"
```

**Dry-run acceptance:** create two local users; one user’s Cookie cannot read `GET /api/auth/me` after logout or access an endpoint using the other user’s raw token.

---

### Task 4: Implement encrypted DataConnection storage

**Depends on:** Task 3

**Estimated review size:** 1 PR; cryptography and connection CRUD

**Files:**
- Create: `packages/dataworks-core/src/data-connection.ts`
- Create: `packages/dataworks-control/migration/0002_data_connections.sql`
- Create: `packages/dataworks-control/src/secret/keyring.ts`
- Create: `packages/dataworks-control/src/secret/store.ts`
- Create: `packages/dataworks-control/src/data-connection/repo.ts`
- Create: `packages/dataworks-control/src/http/data-connection-api.ts`
- Modify: `packages/dataworks-control/src/schema.ts`
- Modify: `packages/dataworks-control/src/http/server.ts`
- Test: `packages/dataworks-control/test/data-connection.integration.test.ts`
- Test: `packages/dataworks-control/test/secret-store.test.ts`

**Interfaces:**
- Produces: `DataConnection.Info`, `SecretStore.put/ref/delete`, `DataConnectionRepo.resolveCredential(userID, connectionID): Effect<RedactedCredential>`, CRUD `/api/data-connections`.

- [ ] **Step 1: Write the cryptographic round-trip and nonce-rotation test**

```ts
import { describe, expect, test } from "bun:test"
import { SecretStore } from "../src/secret/store"

test("encrypts without plaintext and rotates nonce", async () => {
  const store = await SecretStore.test({ root: tempDir, masterKey: new Uint8Array(32).fill(7) })
  await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
  const first = await Bun.file(`${tempDir}/secrets.dat`).arrayBuffer()
  expect(new TextDecoder().decode(first)).not.toContain("secret-value")
  await store.put("connection:a", { accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
  const second = await Bun.file(`${tempDir}/secrets.dat`).arrayBuffer()
  expect(Buffer.from(first).equals(Buffer.from(second))).toBeFalse()
  expect(await store.ref("connection:a")).toEqual({ accessKeyId: "LTAI_TEST", accessKeySecret: "secret-value" })
})
```

- [ ] **Step 2: Run it and verify failure**

Run:

```bash
bun test packages/dataworks-control/test/secret-store.test.ts
```

Expected: FAIL because `SecretStore` is missing.

- [ ] **Step 3: Implement the encrypted file format**

Use:

```text
16-byte magic/version: DWA\0SECRETSv1\0\0\0
12-byte random nonce
AES-256-GCM ciphertext+tag of UTF-8 JSON
```

Write to `secrets.dat.tmp`, `fsync`, then atomic rename. Validate magic/version before decryption. Keep decrypted values wrapped in Effect `Redacted`; provide a custom logger serializer that outputs `[REDACTED]` for `Redacted` and keys matching `/secret|token|password|access.?key/i`.

- [ ] **Step 4: Implement system keyring with a test adapter**

Production uses `@napi-rs/keyring@1.3.0` service=`dataworks-agent`, account=`master-key-v1`. Tests inject an in-memory 32-byte key. If system keyring is unavailable, startup returns a typed `KeyringUnavailable` error with instructions; do not silently write a plaintext key file. The Argon2id fallback is a separate explicit CLI mode `--passphrase`, not an automatic fallback.

- [ ] **Step 5: Write and implement connection CRUD integration**

Test:

```ts
const created = await api.post("/api/data-connections", {
  name: "staging",
  region: "cn-hangzhou",
  accessKeyId: "LTAI_TEST_1234",
  accessKeySecret: "secret-value",
  writeEnabled: false,
})
expect(created).toMatchObject({ name: "staging", accessKeyDisplay: "LTAI_T***1234", writeEnabled: false })
expect(JSON.stringify(created)).not.toContain("secret-value")
expect((await otherUserApi.get("/api/data-connections")).length).toBe(0)
```

`DataConnectionTable` stores metadata and a `secret_ref`; it never stores AK/SK. Add it through `migration/0002_data_connections.sql`, run the migration from an auth-only database fixture, and assert the existing admin/session rows survive unchanged.

- [ ] **Step 6: Run tests and inspect logs/SQLite**

Run:

```bash
bun test packages/dataworks-control/test/secret-store.test.ts packages/dataworks-control/test/data-connection.integration.test.ts
bun run --cwd packages/dataworks-control typecheck
```

Expected: PASS. Search test temp files for `secret-value`; expected no matches outside process output asserted by the test.

- [ ] **Step 7: Commit**

```bash
git add packages/dataworks-core packages/dataworks-control bun.lock
git commit -m "feat(credentials): encrypt data connections locally"
```

**Dry-run acceptance:** connection CRUD works without Alibaba Cloud access; API responses and logs show only the masked AccessKey ID.

---

### Task 5: Add isolated per-user OpenCode worker supervision and proxying

**Depends on:** Tasks 3–4

**Estimated review size:** 2 PRs recommended: worker backend/lifecycle, then proxy/egress security

**Files:**
- Create: `packages/dataworks-control/src/worker/backend.ts`
- Create: `packages/dataworks-control/src/worker/native.ts`
- Create: `packages/dataworks-control/src/worker/oci.ts`
- Create: `packages/dataworks-control/src/worker/paths.ts`
- Create: `packages/dataworks-control/src/worker/supervisor.ts`
- Create: `packages/dataworks-control/src/worker/token.ts`
- Create: `packages/dataworks-control/src/proxy/egress.ts`
- Create: `packages/dataworks-control/src/proxy/http.ts`
- Create: `packages/dataworks-control/src/proxy/websocket.ts`
- Modify: `packages/dataworks-control/src/http/server.ts`
- Create: `scripts/fake-opencode-worker.ts`
- Test: `packages/dataworks-control/test/worker-isolation.integration.test.ts`
- Test: `packages/dataworks-control/test/worker-oci.integration.test.ts`
- Test: `packages/dataworks-control/test/egress-policy.integration.test.ts`

**Interfaces:**
- Produces: `WorkerBackend.start(input)`, `WorkerSupervisor.acquire(userID)`, `WorkerHandle { url, authorization, root, dispose }`, same-origin `/opencode/*` HTTP/WS proxy, and an allowlisted worker egress proxy.

- [ ] **Step 1: Write native-process, OCI, and egress isolation tests**

The native test starts the control plane with `DATAWORKS_AGENT_MODE=single-user-dev` and uses `scripts/fake-opencode-worker.ts`. The fake worker exposes `/env` returning only its effective `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `HOME`, and received Basic username (never password).

Assertions:

```ts
expect(workerA.root).not.toBe(workerB.root)
expect(envA.XDG_DATA_HOME).toContain(userA.id)
expect(envB.XDG_DATA_HOME).toContain(userB.id)
expect(envA.XDG_DATA_HOME).not.toBe(envB.XDG_DATA_HOME)
expect((await userA.get(`/opencode/__test/user/${userB.id}`)).status).toBe(404)
```

The OCI test uses a dedicated fake-worker image and asserts:

```ts
expect(inspect.Config.User).not.toBe("")
expect(inspect.HostConfig.ReadonlyRootfs).toBeTrue()
expect(inspect.HostConfig.CapDrop).toContain("ALL")
expect(inspect.HostConfig.SecurityOpt).toContain("no-new-privileges")
expect(inspect.HostConfig.NetworkMode).not.toBe("host")
expect(inspect.Mounts.every((mount) => mount.Source.startsWith(userA.root) || approvedProjects.has(mount.Source))).toBeTrue()
```

Inside the container, `/host-home`, the control-plane database, `secrets.dat`, and user B’s root must not exist. The egress test requests `http://169.254.169.254`, `http://127.0.0.1`, an RFC1918 address, and an unapproved public host; all are denied before connection. An allowlisted fake Provider host succeeds.

- [ ] **Step 2: Run and verify failure**

Run:

```bash
bun test packages/dataworks-control/test/worker-isolation.integration.test.ts packages/dataworks-control/test/worker-oci.integration.test.ts packages/dataworks-control/test/egress-policy.integration.test.ts
```

Expected: FAIL because supervisor/proxy are absent.

- [ ] **Step 3: Implement deterministic private roots**

For each authenticated user create:

```text
<app-data>/users/<user_id>/home
<app-data>/users/<user_id>/data
<app-data>/users/<user_id>/config
<app-data>/users/<user_id>/cache
```

Pass those as `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`. On Windows also set the OpenCode-specific path flags/env discovered from its `Global.Path` implementation so OpenCode does not fall back to the real user profile. Reject user IDs not matching the branded ID schema before path construction; call `realpath` on the parent and enforce containment.

- [ ] **Step 4: Implement native and OCI worker backends**

`NativeWorkerBackend` uses `Bun.spawn`:

```ts
[opencodeBinary, "serve", "--hostname", "127.0.0.1", "--port", "0"]
```

It is allowed only when all are true: `DATAWORKS_AGENT_MODE=single-user-dev`, control plane binds loopback, database contains at most one enabled user, and environment is not production. Violation is a fatal startup error.

`OciWorkerBackend` uses pinned `dockerode@5.0.1` (Apache-2.0) to access the local OCI-compatible Docker Engine API. It creates a per-user container with:

```text
User: non-root numeric UID
ReadonlyRootfs: true
CapDrop: [ALL]
SecurityOpt: [no-new-privileges]
PidsLimit: 256
Memory: configured default 2 GiB
NanoCpus: configured default 2 cores
NetworkMode: dedicated internal bridge, never host
Tmpfs: /tmp:size=256m,noexec,nosuid,nodev
Mounts: user root + administrator-approved project roots only
```

Both backends set `OPENCODE_SERVER_USERNAME=dwa-worker` and a 32-byte random `OPENCODE_SERVER_PASSWORD`. For native mode, the supervisor binds a temporary loopback listener to obtain a free port, closes it immediately before spawn, passes that explicit port to OpenCode, and retries up to three times on address-in-use. OCI workers listen on container port `4096`; the port is reachable only on the dedicated private bridge and is never published to a host interface.

- [ ] **Step 5: Proxy browser traffic and enforce worker egress**

The browser sends only `dwa_session`; the reverse proxy first applies the same-origin/CSRF gate, strips browser `Authorization`, `Cookie`, `auth_token`, forwarding headers, and hop-by-hop headers, then injects worker Basic auth. For WebSocket upgrades, authenticate the browser Cookie and validate `Origin` before dialing the worker. Cap body size to 50 MB and propagate AbortSignal on disconnect.

Worker HTTP(S) uses an explicit control-plane proxy. Resolve DNS on every connection and reject loopback, link-local, multicast, RFC1918/private IPv6, and cloud metadata addresses after every redirect. Allow only configured LLM Provider/software-source hostnames. The internal DataWorks callback is not reached through the general egress proxy; it uses a separate private route plus scoped worker token.

- [ ] **Step 6: Implement lifecycle rules**

- Single worker per user per control-plane process.
- Concurrent acquire calls coalesce.
- Idle shutdown after 900 seconds with no active HTTP/WS requests.
- Crash backoff: 1s, 2s, 5s, then mark unhealthy after 3 crashes/60s.
- Control-plane shutdown drains workers for 5 seconds then force-kills.

- [ ] **Step 7: Run integration and a real OpenCode smoke check**

Run:

```bash
bun test packages/dataworks-control/test/worker-isolation.integration.test.ts packages/dataworks-control/test/worker-oci.integration.test.ts packages/dataworks-control/test/egress-policy.integration.test.ts
DATAWORKS_AGENT_DRY_RUN=1 bun run --cwd packages/dataworks-control dev
```

With two test users in OCI mode, request `/opencode/global/health` through each Cookie. Expected: 200 from two distinct private containers; direct anonymous access returns 401. In native single-user mode, one user succeeds and enabling a second user causes startup/acquire to fail with `NativeWorkerMultiUserDenied`.

- [ ] **Step 8: Commit**

```bash
git add packages/dataworks-control scripts/fake-opencode-worker.ts
git commit -m "feat(workers): add isolated worker backends"
git commit -m "feat(security): proxy worker traffic safely"
```

**Dry-run acceptance:** two OCI-backed users create independent OpenCode sessions; stopping one container leaves the other healthy; host private files are absent; metadata/private/unapproved egress is blocked. Native mode accepts only one loopback development user.

---

### Task 6: Add the streaming LLM credential gateway

**Depends on:** Tasks 4–5

**Estimated review size:** 2 PRs recommended: gateway/auth strategies, then OpenCode worker routing/provider UI

**Files:**
- Create: `packages/dataworks-core/src/llm-connection.ts`
- Create: `packages/dataworks-control/migration/0003_llm_connections.sql`
- Create: `packages/dataworks-control/src/llm/repo.ts`
- Create: `packages/dataworks-control/src/llm/gateway.ts`
- Create: `packages/dataworks-control/src/llm/policy.ts`
- Create: `packages/dataworks-control/src/llm/auth/static-header.ts`
- Create: `packages/dataworks-control/src/llm/auth/query-key.ts`
- Create: `packages/dataworks-control/src/llm/auth/aws-sigv4.ts`
- Create: `packages/dataworks-control/src/llm/auth/gcp-oauth.ts`
- Create: `packages/dataworks-control/src/llm/auth/oauth-broker.ts`
- Create: `packages/dataworks-control/src/http/llm-connection-api.ts`
- Create: `packages/dataworks-control/src/http/llm-gateway-api.ts`
- Create: `packages/dataworks-control/src/worker/provider-config.ts`
- Test: `tests/integration/dry-run/llm-gateway.test.ts`
- Test: `tests/integration/dry-run/llm-egress-policy.test.ts`
- Test: `tests/integration/dry-run/worker-secret-absence.test.ts`
- Modify: `packages/app/src/components/dialog-connect-provider.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`

**Interfaces:**
- Produces: `LlmConnection.Info`, `CredentialInjector`, `/api/llm-connections`, `/internal/llm/:connectionID/*`, and per-worker non-secret Provider configuration.

- [ ] **Step 1: Write a real streaming gateway integration test**

Start a local fake Provider that records headers and streams three SSE chunks. Create an encrypted `LlmConnection` with `authStrategy="static_header"`, then call the gateway using only the worker token:

```ts
const response = await workerFetch(`/internal/llm/${connection.id}/v1/messages`, {
  method: "POST",
  headers: { authorization: `Bearer ${workerToken}`, "content-type": "application/json" },
  body: JSON.stringify({ model: "fake-model", messages: [{ role: "user", content: "hello" }] }),
})
expect(response.headers.get("content-type")).toContain("text/event-stream")
expect(await response.text()).toContain("data: [DONE]")
expect(fakeProvider.last.headers.get("x-api-key")).toBe("provider-secret")
expect(fakeProvider.last.headers.get("authorization")).not.toContain(workerToken)
```

- [ ] **Step 2: Write worker-secret-absence and egress-policy tests**

Inspect the worker environment, generated OpenCode config, mounted files, process arguments, and `/proc/<pid>/environ` inside the OCI test container. Assert none contain `provider-secret`. Create a `prompt_only` project and assert a full-file automatic context request is denied; explicitly attach a small file and assert it passes after user approval. Assert redirects to a non-allowlisted host or private IP are denied.

- [ ] **Step 3: Run and verify failures**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/llm-gateway.test.ts tests/integration/dry-run/llm-egress-policy.test.ts tests/integration/dry-run/worker-secret-absence.test.ts
```

Expected: FAIL because gateway/connections do not exist.

- [ ] **Step 4: Define LLM connection and injector contracts**

```ts
export interface CredentialInjector {
  inject(input: {
    request: Request
    upstream: URL
    credential: Redacted.Redacted<LlmCredential>
  }): Effect.Effect<Request, LlmGatewayError>
}
```

`LlmConnection` contains user ID, provider ID, allowed models, upstream origin, auth strategy, encrypted `secret_ref`, enabled flag, and data-classification allowlist. The upstream origin is administrator/user configuration stored server-side and is never taken from the worker request. Add it through `0003_llm_connections.sql`; shift later migration numbers forward if implementation already created them.

- [ ] **Step 5: Implement streaming reverse proxy and credential injectors**

- `static_header`: bearer, `x-api-key`, Basic, or named static header.
- `query_key`: inject into an allowlisted query parameter and strip any worker-supplied copy.
- `aws_sigv4`: sign server-side with the configured service/region and stored AWS credential.
- `gcp_oauth`: obtain/cache a short-lived access token server-side using stored service-account/ADC material.
- `oauth_broker`: server-side refresh/access token store and callback flow; Provider adapters must implement it explicitly.

The gateway streams request/response without buffering, caps request body at 20 MB, enforces 10-minute maximum stream duration, strips hop-by-hop/cookie/forwarded headers, validates the worker token’s user/worker/audience, enforces model allowlist, and logs only IDs/status/duration/token usage—not prompt or response bodies.

- [ ] **Step 6: Generate non-secret worker Provider configuration**

For each enabled LLM connection, generate the corresponding OpenCode Provider config with:
- base URL = control-plane internal gateway URL;
- API key/header = short-lived worker token or fixed non-secret marker required by the SDK;
- allowed models only;
- no provider secret, refresh token, cloud credential, or original upstream URL if it would enable bypass.

Single-user development may opt into OpenCode’s native Provider storage. Multi-user/production startup scans worker config/auth databases and refuses to start if real Provider credentials are present.

- [ ] **Step 7: Integrate safe Provider management into the existing OpenCode UI**

Reuse the current connect-provider dialog but route multi-user credential entry to `/api/llm-connections`. Label Provider connection modes accurately. Providers with no implemented safe injector/broker show “Unavailable in multi-user mode” and a reason; they are not silently downgraded. Add English and Chinese copy.

- [ ] **Step 8: Run integrations and a real OpenCode provider turn**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/llm-gateway.test.ts tests/integration/dry-run/llm-egress-policy.test.ts tests/integration/dry-run/worker-secret-absence.test.ts
bun run --cwd packages/dataworks-control typecheck
bun run --cwd packages/opencode typecheck
bun run --cwd packages/app typecheck
```

Start an actual worker configured for the fake Provider gateway and complete one streaming OpenCode Session turn. Expected: normal Session events, no secret in worker state, and fake Provider receives the server-injected credential.

- [ ] **Step 9: Commit reviewable slices**

```bash
git commit -m "feat(llm): proxy provider credentials safely"
git commit -m "feat(app): manage secure llm connections"
```

**Dry-run acceptance:** a real OpenCode worker completes a streamed model turn while no real Provider credential exists in its environment/files/database; policy and redirect bypass attempts fail.

---

## M2 — DataWorks Data Plane

### Task 7: Implement DataWorks OpenAPI and dry-run adapters

**Depends on:** Tasks 4–5

**Estimated review size:** 1 PR; read-only DataWorks adapter slice

**Files:**
- Create: `packages/dataworks-core/src/client.ts`
- Create: `packages/dataworks-control/src/dataworks/openapi.ts`
- Create: `packages/dataworks-control/src/dataworks/dry-run.ts`
- Create: `packages/dataworks-control/src/dataworks/service.ts`
- Create: `packages/dataworks-control/src/http/dataworks-api.ts`
- Create: `tests/fixtures/dataworks/projects.json`
- Create: `tests/fixtures/dataworks/jobs.json`
- Test: `tests/integration/dry-run/dataworks-openapi.test.ts`
- Test: `tests/integration/staging/dataworks-openapi.test.ts`
- Modify: `packages/dataworks-control/package.json`

**Interfaces:**
- Produces: `DataWorksService.listProjects`, `listJobs`, `getJobStatus`, `tableLineage`; `/api/dataworks/projects`, `/api/dataworks/jobs`, `/api/dataworks/jobs/:id`.

- [ ] **Step 1: Write the dry-run API integration test**

```ts
test("returns sanitized fixture projects for the selected connection", async () => {
  const response = await api.get(`/api/dataworks/projects?connectionID=${connection.id}`)
  expect(response.status).toBe(200)
  expect(await response.json()).toEqual([
    { id: 10001, name: "dwa_staging", envType: "DEV", region: "cn-hangzhou" },
  ])
})
```

The fixture must contain synthetic IDs/names, never a production payload copied verbatim.

- [ ] **Step 2: Run and verify failure**

Run:

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/dataworks-openapi.test.ts
```

Expected: FAIL because the API is missing.

- [ ] **Step 3: Define an adapter interface with exact error types**

```ts
export interface DataWorksClient {
  listProjects(input: { region: string; pageNumber: number; pageSize: number }): Effect.Effect<ProjectPage, DataWorksError>
  listJobs(input: { projectID: number; pageNumber: number; pageSize: number }): Effect.Effect<JobPage, DataWorksError>
  getJobStatus(input: { projectID: number; instanceID: number }): Effect.Effect<JobStatus, DataWorksError>
  tableLineage(input: { projectID: number; tableName: string }): Effect.Effect<Lineage, DataWorksError>
}
```

Errors are tagged: `Unauthorized`, `Forbidden`, `RateLimited { retryAfterMs }`, `NotFound`, `UpstreamUnavailable`, `InvalidResponse`.

- [ ] **Step 4: Implement the official SDK adapter**

Pin and use `@alicloud/dataworks-public20200518@10.0.0`, `@alicloud/openapi-client@0.4.15`, `@alicloud/credentials@2.4.5`. Instantiate clients per `{ connectionID, region }` cache key with a 10-minute idle TTL. Resolve credentials from `DataConnectionRepo`; never read them from environment for browser requests.

- [ ] **Step 5: Implement dry-run adapter and HTTP pagination**

Dry-run reads fixtures and returns deterministic pages. HTTP validates `pageSize` 1–100 and integer IDs; maps typed errors to 400/401/403/404/429/502 without exposing SDK response bodies containing credential material.

- [ ] **Step 6: Run dry-run integration and typecheck**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/dataworks-openapi.test.ts
bun run --cwd packages/dataworks-control typecheck
```

Expected: PASS.

- [ ] **Step 7: Add the real staging contract**

`tests/integration/staging/dataworks-openapi.test.ts` must:
- exit with a clear failure when invoked in staging mode without required secrets;
- list projects using the dedicated staging AK;
- assert the configured project ID is present;
- get one known read-only job status;
- write sanitized evidence to `artifacts/staging/dataworks-openapi.json`.

Run manually:

```bash
DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0 bun test tests/integration/staging/dataworks-openapi.test.ts
```

Expected: PASS with real HTTP requests and no write API calls.

- [ ] **Step 8: Commit**

```bash
git add packages/dataworks-core packages/dataworks-control tests bun.lock
git commit -m "feat(dataworks): add openapi adapter"
```

**Dry-run acceptance:** project/job APIs return fixture data and malformed/foreign connection IDs are rejected.

---

### Task 8: Add the supervised PyODPS JSON-RPC sidecar

**Depends on:** Task 7

**Estimated review size:** 1 PR; Python sidecar plus Bun supervisor

**Files:**
- Create: `sidecars/pyodps/pyproject.toml`
- Create: `sidecars/pyodps/uv.lock`
- Create: `sidecars/pyodps/src/dwa_pyodps/__main__.py`
- Create: `sidecars/pyodps/src/dwa_pyodps/protocol.py`
- Create: `sidecars/pyodps/src/dwa_pyodps/query.py`
- Create: `sidecars/pyodps/tests/test_protocol.py`
- Create: `packages/dataworks-control/src/odps/protocol.ts`
- Create: `packages/dataworks-control/src/odps/sidecar.ts`
- Create: `packages/dataworks-control/src/odps/sql-policy.ts`
- Create: `packages/dataworks-control/src/odps/service.ts`
- Create: `tests/fixtures/odps/query.json`
- Test: `tests/integration/dry-run/pyodps-sidecar.test.ts`
- Test: `tests/integration/staging/pyodps-sidecar.test.ts`

**Interfaces:**
- Produces: `OdpsService.query({ credential, endpoint, project, sql, timeoutMs, maxRows, maxBytes, signal })`; NDJSON messages `query`, `cancel`, `result`, `error`, `health`.

- [ ] **Step 1: Define the NDJSON protocol in both languages**

Request:

```json
{"id":"req_01","method":"query","params":{"endpoint":"...","project":"...","sql":"select 1","timeout_ms":300000,"max_rows":10000,"max_bytes":10485760,"access_key_id":"...","access_key_secret":"..."}}
```

Success:

```json
{"id":"req_01","result":{"columns":[{"name":"_c0","type":"bigint"}],"rows":[[1]],"truncated":false,"instance_id":"...","duration_ms":123}}
```

Error:

```json
{"id":"req_01","error":{"code":"TIMEOUT","message":"Query exceeded 300000ms","retryable":false}}
```

Cancellation:

```json
{"id":"req_01","method":"cancel"}
```

- [ ] **Step 2: Write protocol tests before implementation**

Python tests verify malformed JSON, missing fields, row/byte truncation, and cancellation. Bun integration starts the actual Python process through `uv run`, sends `health`, sends dry-run `select 1`, and kills/restarts the child once.

- [ ] **Step 3: Run tests and verify failure**

```bash
uv run --project sidecars/pyodps pytest sidecars/pyodps/tests -q
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/pyodps-sidecar.test.ts
```

Expected: FAIL because sidecar implementation is missing.

- [ ] **Step 4: Implement the Python sidecar**

Pin `pyodps==0.13.0`; use Python `>=3.12,<3.15`. Read one JSON object per stdin line; write only protocol JSON to stdout and diagnostics to stderr. In real mode use `ODPS(...).execute_sql(sql)` and stream records until `max_rows` or `max_bytes`; cancel the instance on timeout/Abort. Never log params containing credentials or SQL literals at info level.

- [ ] **Step 5: Implement the Bun supervisor**

Start:

```bash
uv run --project sidecars/pyodps python -m dwa_pyodps
```

Maintain one sidecar per control-plane process, correlate requests by ID, cap in-flight queries at 4, restart after unexpected exit with 1s/2s/5s backoff, reject all pending requests on crash, and propagate AbortSignal via `cancel`. Parse stdout line length with a 16 MB hard cap.

- [ ] **Step 6: Add SQL safety gates**

`dw_run_sql` accepts exactly one read-only statement. Implement a local tokenizer in `src/odps/sql-policy.ts` that emits words/punctuation while skipping whitespace, line/block comments, and single/double/backtick-quoted bodies. Reject a second top-level semicolon/token stream and reject top-level commands other than `SELECT`, `WITH ... SELECT`, `SHOW`, `DESC`, or `DESCRIBE`. Reject tokens `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `TRUNCATE`, `CALL`, `SET`, `ADD`, `REMOVE`, `PUT`, and `GET` outside quoted bodies. Tests must cover quoted semicolons, comments, nested CTEs, `WITH ... INSERT`, and mixed casing. Do not use a `startsWith("select")` check.

- [ ] **Step 7: Run dry-run and Python tests**

```bash
uv run --project sidecars/pyodps pytest sidecars/pyodps/tests -q
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/pyodps-sidecar.test.ts
bun run --cwd packages/dataworks-control typecheck
```

Expected: PASS.

- [ ] **Step 8: Run staging query acceptance**

```bash
DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0 bun test tests/integration/staging/pyodps-sidecar.test.ts
```

The test runs `SELECT 1`, then one bounded query against a staging fixture table and records columns, row count, instance ID, and duration—never row contents containing business data.

- [ ] **Step 9: Commit**

```bash
git add sidecars packages/dataworks-control tests
git commit -m "feat(odps): add supervised pyodps queries"
```

**Dry-run acceptance:** the real sidecar process starts on Windows and Linux CI, answers health/query, truncates results, honors cancellation, and restarts after forced termination.

---

### Task 9: Add MCP fallback, auditing, and one-time write tickets

**Depends on:** Tasks 6–8

**Estimated review size:** 1 PR; security-sensitive write-control slice

**Files:**
- Create: `packages/dataworks-core/src/audit.ts`
- Create: `packages/dataworks-control/migration/0004_audit_tickets.sql`
- Create: `packages/dataworks-control/src/mcp/client.ts`
- Create: `packages/dataworks-control/src/audit/repo.ts`
- Create: `packages/dataworks-control/src/write-ticket/service.ts`
- Create: `packages/dataworks-control/src/http/audit-api.ts`
- Modify: `packages/dataworks-control/src/schema.ts`
- Modify: `packages/dataworks-control/src/dataworks/service.ts`
- Test: `tests/integration/dry-run/audit-write-ticket.test.ts`
- Test: `tests/integration/dry-run/mcp-fallback.test.ts`

**Interfaces:**
- Produces: `AuditRepo.append/list`, `WriteTicket.issue/consume`, `McpDataWorksClient.call`, internal `POST /internal/dataworks/execute` requiring worker token and optional one-time ticket.

- [ ] **Step 1: Write an end-to-end write-ticket replay test**

```ts
const ticket = await user.issueWriteTicket({ connectionID, tool: "dw_rerun_job", argsHash, reason: "retry failed staging job" })
expect((await worker.execute({ ticket, tool: "dw_rerun_job", args })).status).toBe(200)
expect((await worker.execute({ ticket, tool: "dw_rerun_job", args })).status).toBe(409)
expect(await audit.latest()).toMatchObject({ userID: user.id, tool: "dw_rerun_job", reason: "retry failed staging job", outcome: "success" })
```

- [ ] **Step 2: Run and verify failure**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/audit-write-ticket.test.ts
```

Expected: FAIL because ticket/audit services do not exist.

- [ ] **Step 3: Add audit and ticket tables**

Add both tables with `migration/0004_audit_tickets.sql`; upgrade a `0003` fixture and assert users, sessions, DataConnections, and LLM connections remain readable.

Audit fields: `id`, `user_id`, `connection_id`, `session_id`, `tool`, `permission`, `args_hash`, `reason`, `outcome`, `error_code`, `duration_ms`, `time_created`. Never store raw args, SQL, credentials, or result rows by default.

Ticket fields: random 32-byte `token_hash`, `user_id`, `connection_id`, `session_id`, `tool`, `args_hash`, `time_expires` (60 seconds), `time_consumed`. Consume atomically in a transaction.

- [ ] **Step 4: Implement internal worker authentication**

The worker receives a short-lived signed internal token scoped to `{ userID, workerID, expires }`; the control plane validates signature and worker process identity. The plugin passes this token in `Authorization: Bearer`; browser requests to `/internal/*` are always rejected even with a browser Cookie.

- [ ] **Step 5: Implement MCP adapter as an explicit fallback**

Use OpenCode’s existing MCP client abstractions where possible. Configure MCP endpoints per `DataConnection`; secret headers live in `SecretStore`. `dw_mcp_call` can call only an allowlisted server/tool pair. MCP failures do not silently fall back from OpenAPI when the operation is a write; caller chooses the adapter explicitly.

- [ ] **Step 6: Run dry-run integrations**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/audit-write-ticket.test.ts tests/integration/dry-run/mcp-fallback.test.ts
```

Expected: PASS; replay is rejected; audit rows contain hashes, not arguments.

- [ ] **Step 7: Commit**

```bash
git add packages/dataworks-core packages/dataworks-control tests
git commit -m "feat(audit): gate dataworks writes"
```

**Dry-run acceptance:** write simulation requires a ticket, consumes it once, and creates a user-visible audit row; disabling `writeEnabled` prevents ticket issuance.

---

## M3 — DataWorks Agent Tools

### Task 10: Create the OpenCode DataWorks plugin and read tools

**Depends on:** Tasks 6–9

**Estimated review size:** 1 PR; plugin plus read-only tool loop

**Files:**
- Create: `packages/dataworks-plugin/package.json`
- Create: `packages/dataworks-plugin/tsconfig.json`
- Create: `packages/dataworks-plugin/src/index.ts`
- Create: `packages/dataworks-plugin/src/client.ts`
- Create: `packages/dataworks-plugin/src/context.ts`
- Create: `packages/dataworks-plugin/src/tools/projects.ts`
- Create: `packages/dataworks-plugin/src/tools/tables.ts`
- Create: `packages/dataworks-plugin/src/tools/sql.ts`
- Create: `packages/dataworks-plugin/src/tools/jobs.ts`
- Create: `packages/dataworks-plugin/src/tools/lineage.ts`
- Create: `packages/dataworks-plugin/test/plugin.integration.test.ts`
- Modify: root OpenCode config fixture or managed plugin config to load `@dataworks-agent/plugin`

**Interfaces:**
- Produces plugin tools: `dw_list_projects`, `dw_list_tables`, `dw_describe_table`, `dw_run_sql`, `dw_table_lineage`, `dw_list_jobs`, `dw_get_job_status`, `dw_alert_list`, `dw_mcp_call`.

- [ ] **Step 1: Write a real ToolRegistry integration test**

The test boots the OpenCode AppLayer in a temporary project with the plugin configured and a fake control-plane server. It calls `ToolRegistry.ids()` and executes `dw_list_projects` through the resolved tool definition:

```ts
expect(await run(ToolRegistry.ids())).toContain("dw_list_projects")
const tool = (await run(ToolRegistry.all())).find((item) => item.id === "dw_list_projects")!
const result = await run(tool.execute({ connectionID }, toolContext))
expect(result.output).toContain("dwa_staging")
```

- [ ] **Step 2: Run and verify failure**

```bash
bun test packages/dataworks-plugin/test/plugin.integration.test.ts
```

Expected: FAIL because plugin/tools are absent.

- [ ] **Step 3: Implement a narrow internal client**

`ControlPlaneClient.execute` posts `{ tool, args, sessionID }` to `/internal/dataworks/execute`, adds the worker token, propagates abort, parses typed errors, and caps response body to 10 MB. It never accepts a base URL or token from model-provided tool args.

- [ ] **Step 4: Implement read tools using `@opencode-ai/plugin`**

Each tool uses `tool({ description, args, execute })`. Parameters identify business inputs, not secrets. Example:

```ts
export const dw_list_projects = tool({
  description: "List DataWorks projects visible through the selected data connection.",
  args: {
    connectionID: tool.schema.string().describe("Configured DataConnection ID"),
    page: tool.schema.number().int().min(1).default(1),
  },
  async execute(args, ctx) {
    await ctx.ask({ permission: "dw_read", patterns: [args.connectionID], always: [], metadata: { tool: "dw_list_projects" } })
    return client(ctx).execute("dw_list_projects", args)
  },
})
```

`dw_run_sql` requires `dw_query` permission and sends `maxRows <= 10000`, `timeoutMs <= 300000`.

- [ ] **Step 5: Register plugin without a core ToolRegistry patch**

Use OpenCode’s external plugin loader via managed/user config. For packaged deployment, generate the user worker config with:

```json
{
  "plugin": ["@dataworks-agent/plugin"]
}
```

Do not import DataWorks tools into `packages/opencode/src/tool/registry.ts` unless plugin loading proves unable to satisfy startup/permission requirements; that exception needs two-reviewer approval and an `UPSTREAM.md` patch note.

- [ ] **Step 6: Run plugin and OpenCode package tests**

```bash
bun test packages/dataworks-plugin/test/plugin.integration.test.ts
bun run --cwd packages/dataworks-plugin typecheck
bun run --cwd packages/opencode typecheck
```

Expected: PASS.

- [ ] **Step 7: Run a dry-run agent loop**

Start control plane + worker with a deterministic local test provider that emits a `dw_list_projects` tool call. Send a prompt through the actual OpenCode session API. Assert event stream includes the tool call/result and final response names `dwa_staging`.

Run:

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/agent-tool-loop.test.ts
```

Expected: PASS without cloud/LLM network calls.

- [ ] **Step 8: Commit**

```bash
git add packages/dataworks-plugin tests package.json bun.lock
git commit -m "feat(plugin): add dataworks read tools"
```

**Dry-run acceptance:** a real OpenCode SessionV2 turn invokes `dw_list_projects` and `dw_run_sql`, emits normal OpenCode events, and produces a final assistant response.

---

### Task 11: Add write tools, PermissionV1 confirmation, and filesystem protection

**Depends on:** Tasks 9–10

**Estimated review size:** 1 PR; high-security tool and path policy

**Files:**
- Create: `packages/dataworks-plugin/src/tools/write.ts`
- Create: `packages/dataworks-plugin/src/permission.ts`
- Create: `packages/dataworks-core/src/private-path.ts`
- Create: `packages/opencode/src/tool/private-path.ts`
- Modify: `packages/opencode/src/agent/agent.ts`
- Modify: `packages/opencode/src/tool/external-directory.ts`
- Modify: `packages/opencode/src/tool/read.ts`
- Modify: `packages/opencode/src/tool/edit.ts`
- Modify: `packages/opencode/src/tool/write.ts`
- Modify: `packages/opencode/src/tool/apply_patch.ts`
- Modify: `packages/opencode/src/tool/shell.ts`
- Test: `packages/dataworks-plugin/test/write-permission.integration.test.ts`
- Test: `packages/dataworks-core/test/private-path.test.ts`
- Test: `tests/integration/dry-run/filesystem-isolation.test.ts`

**Interfaces:**
- Produces: `dw_rerun_job`, `dw_trigger_supplement`, `dw_pause_schedule`, `dw_alert_silence`; `PrivatePathPolicy.check(realPath, operation, userRoot)`.

- [ ] **Step 1: Write write-tool permission tests**

Test cases:
1. `writeEnabled=false` → tool returns denied before ticket issuance.
2. `writeEnabled=true` → OpenCode emits `permission.asked` with `permission="dw_write"`.
3. Reject reply → no internal execution/audit outcome=`rejected`.
4. Approve with empty reason → 400.
5. Approve with reason → one-time ticket → one execution.

- [ ] **Step 2: Write path escape tests**

Cases must include direct private path, `..`, Windows case-insensitivity, symlink on Unix, junction on Windows, worker A accessing worker B, and allowed project file. Expected private paths always return a typed deny that cannot be overridden by an `always` approval.

- [ ] **Step 3: Run and verify failures**

```bash
bun test packages/dataworks-plugin/test/write-permission.integration.test.ts packages/dataworks-core/test/private-path.test.ts tests/integration/dry-run/filesystem-isolation.test.ts
```

Expected: FAIL because write tools/path policy are missing.

- [ ] **Step 4: Implement write tools**

Each write tool:
- calls `ctx.ask({ permission: "dw_write", patterns: [connectionID, operationTarget], always: [], metadata: { tool, argsHash } })`;
- obtains the user-entered reason from the permission reply flow controlled by the Web app;
- requests a ticket from the control plane;
- executes once with that ticket;
- returns title/output without raw upstream payload.

- [ ] **Step 5: Enforce private-path mandatory denies in the OpenCode tool boundary**

Create `packages/opencode/src/tool/private-path.ts` as the single mandatory guard. It parses control-plane-injected `DWA_PRIVATE_PATHS` (JSON array of absolute roots), resolves the candidate with `path.resolve`, resolves the nearest existing parent with `fs.realpath`, reattaches the missing suffix, performs Windows case-folding, and returns a typed deny before any permission prompt. Call it from `external-directory`, `read`, `edit`, `write`, `apply_patch`, and every shell path discovered by the existing shell parser; add a mandatory deny rule in `agent.ts` so user config cannot turn it into `always allow`. Document these exact core patches in `UPSTREAM.md`. OCI containment remains the production boundary; this patch protects the explicitly limited native single-user mode and prevents accidental mounts from exposing control-plane private paths.

- [ ] **Step 6: Run security integrations and OpenCode regressions**

```bash
bun test packages/dataworks-plugin/test/write-permission.integration.test.ts packages/dataworks-core/test/private-path.test.ts tests/integration/dry-run/filesystem-isolation.test.ts
bun run --cwd packages/opencode test:httpapi
bun run --cwd packages/opencode typecheck
```

Expected: all PASS; existing edit/read/shell operations inside a normal project still work.

- [ ] **Step 7: Commit**

```bash
git add packages/dataworks-plugin packages/dataworks-core packages/opencode UPSTREAM.md tests
git commit -m "feat(security): gate write tools and private paths"
```

**Dry-run acceptance:** browser confirmation visibly blocks a simulated rerun until reason+approval; replay and private-path escape attempts fail and appear in audit events.

---

## M4 — Web Productization

### Task 12: Add authenticated Web shell and DataWorks pages in the OpenCode SolidJS app

**Depends on:** Tasks 3–11

**Estimated review size:** 2 PRs recommended: shell/theme, then pages/flows

**Files:**
- Create: `packages/app/src/context/dataworks.tsx`
- Create: `packages/app/src/pages/dataworks/connections.tsx`
- Create: `packages/app/src/pages/dataworks/explorer.tsx`
- Create: `packages/app/src/pages/dataworks/jobs.tsx`
- Create: `packages/app/src/pages/dataworks/knowledge.tsx`
- Create: `packages/app/src/pages/dataworks/audit.tsx`
- Create: `packages/app/src/components/dataworks/connection-selector.tsx`
- Create: `packages/app/src/components/dataworks/write-confirmation.tsx`
- Create: `packages/app/src/styles/dataworks-theme.css`
- Modify: `packages/app/src/app.tsx`
- Modify: `packages/app/src/pages/layout-new.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`
- Test: `packages/app/src/pages/dataworks/route.test.ts`
- Test: `packages/app/e2e/dataworks.spec.ts`

**Interfaces:**
- Produces routes `/dataworks/connections`, `/dataworks/explorer`, `/dataworks/jobs`, `/dataworks/knowledge`, `/dataworks/audit`; `DataWorksProvider`; write-confirmation UI integrated with OpenCode PermissionProvider.

- [ ] **Step 1: Write route and auth-gate tests**

Test anonymous users are redirected to `/login`; authenticated users see the shell; non-admin users cannot open audit-all-users view; session/chat routes still render under the same providers.

- [ ] **Step 2: Run tests and verify failure**

```bash
bun run --cwd packages/app test:unit -- src/pages/dataworks/route.test.ts
```

Expected: FAIL because routes/context do not exist.

- [ ] **Step 3: Add same-origin DataWorks context**

`DataWorksProvider` calls `/api/auth/me`, `/api/data-connections`, and DataWorks endpoints using `credentials: "include"`; it must not persist credentials/tokens in localStorage. Keep OpenCode SDK traffic under `/opencode` through the existing server context.

- [ ] **Step 4: Apply new-api-inspired visual tokens without replacing OpenCode UI**

Add scoped CSS variables:

```css
:root {
  --dwa-radius: 1rem;
  --dwa-primary: oklch(0.692 0.141 243.716);
  --dwa-border: oklch(0.93 0 0);
  --dwa-success: oklch(0.596 0.145 163.225);
  --dwa-warning: oklch(0.681 0.162 75.834);
  --dwa-danger: oklch(0.577 0.245 27.325);
}
.dark {
  --dwa-surface: oklch(0.235 0 0);
  --dwa-border: oklch(1 0 0 / 10%);
}
```

Map these to existing `packages/ui` primitives and OpenCode typography; do not introduce React/Base UI/TanStack React dependencies.

- [ ] **Step 5: Implement DataWorks navigation and pages**

- Connections: masked AK, region, write toggle, test connection.
- Explorer: project selector, table search, schema/partition detail, bounded SQL editor/results.
- Jobs: filters, status, rerun/supplement/pause actions.
- Knowledge: upload/progress/document status.
- Audit: current user events; admin can filter users.

All lists include loading, empty, partial, rate-limit, and retry states. All copy is added to English and Chinese locale files.

- [ ] **Step 6: Integrate write confirmation**

When OpenCode emits `permission.asked` for `dw_write`, show tool, target, masked connection, and required reason textbox. Approval sends reason to the control plane and then replies to OpenCode permission; rejection replies immediately and creates a rejection audit record.

- [ ] **Step 7: Run unit/typecheck/browser E2E**

```bash
bun run --cwd packages/app typecheck
bun run --cwd packages/app test:unit
DATAWORKS_AGENT_DRY_RUN=1 bun run --cwd packages/app test:e2e -- dataworks.spec.ts
```

Expected: PASS. E2E screenshots saved for login, explorer results, and write confirmation in light and dark mode at 1440×900 and 390×844.

- [ ] **Step 8: Run accessibility check**

Use Playwright + axe (add `@axe-core/playwright`) on login, explorer, and modal. Expected: no serious/critical violations; keyboard can reach navigation, result table, and confirmation controls; focus returns after modal closes.

- [ ] **Step 9: Commit each reviewable UI slice**

```bash
git commit -m "feat(app): add dataworks shell"
git commit -m "feat(app): add dataworks workspace pages"
```

**Dry-run acceptance:** a user logs in, creates a masked fixture connection, browses tables, runs fixture SQL, opens a Session, and confirms/rejects a simulated write without page reload.

---

## M5 — Skills and RAG

### Task 13: Extend OpenCode Skills with DataWorks permissions and tenant isolation

**Depends on:** Tasks 5, 10–12

**Estimated review size:** 1 PR; Skill loader/management API

**Files:**
- Create: `packages/dataworks-core/src/skill.ts`
- Create: `packages/dataworks-control/src/skill/repo.ts`
- Create: `packages/dataworks-control/src/http/skill-api.ts`
- Create: `packages/dataworks-plugin/src/skill-context.ts`
- Modify: `packages/dataworks-plugin/src/index.ts`
- Modify: `packages/app/src/pages/dataworks/skills.tsx`
- Modify: `packages/app/src/app.tsx`
- Modify: `packages/app/src/i18n/en.ts`
- Modify: `packages/app/src/i18n/zh.ts`
- Test: `tests/integration/dry-run/skill-isolation.test.ts`

**Interfaces:**
- Produces: managed/system and per-user `SKILL.md` roots; DataWorks frontmatter extension; Skill management API; OpenCode Skill discovery with user-scoped directories.

- [ ] **Step 1: Write Skill isolation/hot-reload integration**

Create two users with same-named skills but different content. Boot both workers; call OpenCode `skill` tool. Assert each sees only system + own Skill. Modify user A’s `SKILL.md`; dispose/reload instance or trigger supported refresh; assert new content loads without affecting user B.

- [ ] **Step 2: Run and verify failure**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/skill-isolation.test.ts
```

Expected: FAIL because scoped Skill roots are missing.

- [ ] **Step 3: Define one-source Skill metadata**

Use only `SKILL.md` frontmatter:

```yaml
---
name: logistics-anomaly
description: Diagnose logistics order anomalies
triggers: ["物流异常", "order_anomaly"]
allowed_tools: [dw_run_sql, dw_list_tables, dw_describe_table]
forbidden_tools: [dw_rerun_job, dw_trigger_supplement]
max_tool_calls_per_session: 20
write_enabled: false
---
```

Parse with the OpenCode-compatible markdown/frontmatter path; do not create `skill.toml`.

- [ ] **Step 4: Map Skill policy to OpenCode PermissionV1**

`allowed_tools` narrows visibility; `forbidden_tools` becomes mandatory deny; write tools stay deny unless both connection and Skill enable write, then remain `ask`. Enforce `max_tool_calls_per_session` in the plugin hook and return a typed limit result to the model.

- [ ] **Step 5: Implement admin/user storage and API**

System Skills live under control-plane-managed read-only root. User Skills live under `users/<id>/skills`. API validates names, file size <= 1 MB, UTF-8, frontmatter schema, and no symlink/junction. Normal users cannot change system Skills.

- [ ] **Step 6: Run integration and upstream Skill regression**

```bash
DATAWORKS_AGENT_DRY_RUN=1 bun test tests/integration/dry-run/skill-isolation.test.ts
bun run --cwd packages/opencode typecheck
bun run --cwd packages/dataworks-plugin typecheck
```

Expected: PASS; existing OpenCode Skills still load.

- [ ] **Step 7: Commit**

```bash
git add packages/dataworks-core packages/dataworks-control packages/dataworks-plugin packages/app tests
git commit -m "feat(skills): isolate dataworks playbooks"
```

**Dry-run acceptance:** system/user Skills appear in UI and the OpenCode skill tool; forbidden DataWorks tools remain unavailable regardless of prompt injection in Skill content.

---

### Task 14: Add document ingestion and tenant-isolated RAG

**Depends on:** Tasks 3–6, 12–13

**Estimated review size:** 2 PRs recommended: ingestion/indexing, then retrieval/context integration

**Files:**
- Create: `packages/dataworks-core/src/knowledge.ts`
- Create: `packages/dataworks-control/migration/0005_knowledge.sql`
- Create: `packages/dataworks-control/src/knowledge/repo.ts`
- Create: `packages/dataworks-control/src/knowledge/parser-worker.ts`
- Create: `packages/dataworks-control/src/knowledge/parser.ts`
- Create: `packages/dataworks-control/src/knowledge/chunker.ts`
- Create: `packages/dataworks-control/assets/embeddings/manifest.json`
- Create: `scripts/fetch-embedding-model.ts`
- Create: `packages/dataworks-control/src/knowledge/embedder.ts`
- Create: `packages/dataworks-control/src/knowledge/index.ts`
- Create: `packages/dataworks-control/src/http/knowledge-api.ts`
- Create: `packages/dataworks-plugin/src/rag-context.ts`
- Modify: `packages/dataworks-plugin/src/index.ts`
- Modify: `packages/dataworks-control/src/schema.ts`
- Modify: `packages/dataworks-control/package.json`
- Modify: `packages/app/src/pages/dataworks/knowledge.tsx`
- Test: `packages/dataworks-control/test/chunker.test.ts`
- Test: `tests/integration/dry-run/knowledge-rag.test.ts`
- Test: `tests/integration/dry-run/knowledge-isolation.test.ts`
- Test: `packages/app/e2e/dataworks-knowledge.spec.ts`

**Interfaces:**
- Produces: upload/list/delete/reindex/search APIs; `EmbeddingProvider`; LanceDB user/DataConnection filters; per-knowledge-base `egressPolicy`; plugin system-context retrieval.

- [ ] **Step 1: Write bounded chunker unit tests**

Use deterministic text with paragraphs and Unicode. Assert chunks are <= 512 model tokens, overlap is <=64 tokens, source offsets are monotonic, and empty/whitespace input creates no chunks. This pure parser is one of the explicitly allowed unit-test targets.

- [ ] **Step 2: Write real upload/search integration tests**

Upload `.md`, `.txt`, `.docx`, and `.pdf` fixture documents through multipart HTTP. Poll until status=`ready`, then search and assert top result identifies the source and excerpt. Upload a 50 MB + 1 byte file and assert 413. User B search must return no chunks from user A. Create a `local_only` knowledge base and assert attempts to select remote embedding or inject chunks into a remote Provider are denied. Create `approved_providers=["dashscope"]` and assert another Provider remains denied until separately approved.

- [ ] **Step 3: Run and verify failures**

```bash
bun test packages/dataworks-control/test/chunker.test.ts tests/integration/dry-run/knowledge-rag.test.ts tests/integration/dry-run/knowledge-isolation.test.ts
```

Expected: FAIL because knowledge services are absent.

- [ ] **Step 4: Implement safe ingestion**

- Stream uploads to a quarantine temp file; do not buffer 50 MB in memory.
- Allowed MIME/extensions: PDF, DOCX, Markdown, plain text.
- Limits: 50 MB, 1000 pages, 10 minutes parse time.
- Use `pdf-parse@2.4.5` and `mammoth@1.12.0` in a separate parser worker process/container with no network, read-only input mount, 1 GiB memory, 1 CPU, 120-second per-document timeout, and 256 MB output cap; sanitize filenames and never execute embedded content/macros. Killing or timing out parser worker marks only that document failed.
- Move originals under user-private root only after validation; store SHA-256 for dedupe.
- Add knowledge/document/index-job/provider-approval metadata through `migration/0005_knowledge.sql`; upgrade a `0004` fixture and verify existing audit rows remain intact.

- [ ] **Step 5: Implement embeddings and LanceDB**

Pin `@lancedb/lancedb@0.31.0` and `fastembed@2.1.0`. The offline model is fixed to `EmbeddingModel.MLE5Large` (`fast-multilingual-e5-large`, 1024 dimensions, multilingual query/passage prefixes) from `https://storage.googleapis.com/qdrant-fastembed/fast-multilingual-e5-large.tar.gz`. `assets/embeddings/manifest.json` records that URL, upstream model/license metadata, archive SHA-256, extracted file paths, and each extracted file SHA-256. `scripts/fetch-embedding-model.ts` downloads only that allowlisted URL during a controlled asset-update job, verifies archive/extracted hashes, and refuses an empty/uncommitted hash. A second release CI job downloads independently and compares hashes before packaging. Runtime loads the extracted directory through FastEmbed custom/local-path mode and never performs implicit downloads. Dry-run uses a deterministic local hash embedding solely for tests that do not claim semantic quality; acceptance must run the packaged MLE5Large asset. New knowledge bases default to `egressPolicy="local_only"`; remote embedding is available only when its Provider appears in `approvedProviders`, and the approval event is audited. Every row contains `user_id`, optional `connection_id`, `document_id`, source offsets, text, vector. Search applies user filtering inside the LanceDB query, not after retrieval.

- [ ] **Step 6: Integrate RAG with OpenCode plugin**

Use plugin `experimental.chat.system.transform` to inject only top relevant chunks with citations and a strict max token budget. Before injection, compare the knowledge base `egressPolicy` with the active OpenCode Provider: `local_only` permits only a configured local Provider; `approved_providers` requires an exact Provider ID match. Provide an explicit `dw_knowledge_search` tool for user-directed search. Prompt text in uploaded documents is untrusted data and is wrapped as quoted context with an instruction that it cannot alter permissions/tools.

- [ ] **Step 7: Implement rebuild/degradation**

If LanceDB open/search fails, mark index degraded, keep originals, return local keyword search results, and enqueue rebuild. Rebuild writes a new index directory then atomically swaps. LLM/provider failure leaves document parse/status visible and retryable.

- [ ] **Step 8: Run tests and UI E2E**

```bash
bun test packages/dataworks-control/test/chunker.test.ts tests/integration/dry-run/knowledge-rag.test.ts tests/integration/dry-run/knowledge-isolation.test.ts
DATAWORKS_AGENT_DRY_RUN=1 bun run --cwd packages/app test:e2e -- dataworks-knowledge.spec.ts
```

Expected: PASS; citations link to the correct private document but never expose an absolute local path. Browser E2E must show the target Provider and require confirmation before changing a knowledge base from `local_only` to remote-enabled; the decision appears in audit history.

- [ ] **Step 9: Commit reviewable slices**

```bash
git commit -m "feat(knowledge): ingest private documents"
git commit -m "feat(rag): retrieve tenant-scoped context"
```

**Dry-run acceptance:** two users upload different documents and receive isolated retrieval. `local_only` content never reaches a remote test Provider; after explicit Provider-specific approval, only the approved Provider receives cited chunks from the active user.

---

## M6 — Real Acceptance, Packaging, and Release

### Task 15: Complete staging E2E, packaging, release, and upstream-sync rehearsal

**Depends on:** Tasks 1–14

**Estimated review size:** 2 PRs recommended: test/reliability gates, then packaging/release

**Files:**
- Create: `tests/integration/staging/agent-e2e.test.ts`
- Create: `packages/app/e2e/dataworks-staging.spec.ts`
- Create: `scripts/acceptance.ts`
- Create: `scripts/package-dataworks-agent.ts`
- Create: `.github/workflows/release.yml`
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `docs/operations/staging.md`
- Create: `docs/operations/backup-restore.md`
- Create: `docs/operations/upstream-sync.md`
- Create: `docs/security/threat-model.md`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `package.json`

**Interfaces:**
- Produces: `bun run acceptance:dry-run`, `bun run acceptance:staging`, Windows/Linux release artifacts, checksum/SBOM, release-please flow.

- [ ] **Step 1: Write the staging acceptance test first**

The test must perform through public/browser-facing APIs:
1. login and verify cross-origin POST/WebSocket attempts are rejected;
2. select staging DataConnection;
3. list projects/tables;
4. run bounded `SELECT 1` through PyODPS;
5. create OpenCode Session;
6. send prompt that invokes `dw_describe_table` and `dw_run_sql`;
7. observe normal OpenCode event stream and final cited answer;
8. run every enabled write tool against dedicated staging fixtures when `DWA_STAGING_WRITE_TEST=1`: rerun a no-op job, trigger a one-day test supplement, pause then restore a dedicated test schedule, and silence then restore a dedicated test alert; assert final state equals initial state and audit records contain the required reason;
9. when write testing is disabled, assert every write tool remains blocked and do not mark the release staging gate complete;
10. upload/search a synthetic document using the packaged local embedding model;
11. verify audit entries and confirm no prompt/row/secret content appears in logs.

- [ ] **Step 2: Run dry-run full acceptance before staging**

Create root scripts:

```json
"acceptance:dry-run": "DATAWORKS_AGENT_DRY_RUN=1 bun scripts/acceptance.ts dry-run",
"acceptance:staging": "DATAWORKS_AGENT_ENV=staging DATAWORKS_AGENT_DRY_RUN=0 bun scripts/acceptance.ts staging"
```

On Windows, implement env injection inside `scripts/acceptance.ts` rather than relying on POSIX `VAR=value` syntax. Run:

```bash
bun run acceptance:dry-run
```

Expected: starts control plane, two workers, PyODPS sidecar, and browser E2E; all gates pass and artifacts land under `artifacts/acceptance/dry-run/`.

- [ ] **Step 3: Run real staging acceptance**

```bash
bun run acceptance:staging
```

Expected: real DataWorks OpenAPI and MaxCompute requests pass; artifact contains timestamps, upstream request IDs/instance IDs, durations, screenshots, and test account/project identifiers in masked form. No business row contents or secrets are captured.

- [ ] **Step 4: Run failure drills**

Automate and record:
- kill PyODPS mid-query → pending request fails, sidecar restarts;
- kill one user worker → only that user reconnects;
- return 429 from DataWorks → UI shows retry-after;
- corrupt a copy of LanceDB → keyword fallback + rebuild;
- expire browser session during event stream → reconnection requires login and does not leak buffered events;
- attempt private path access → mandatory deny/audit.

Expected: all drills meet documented recovery times; no cross-user effect.

- [ ] **Step 5: Package Windows and Linux artifacts**

Build OpenCode worker using upstream build script and bundle control plane/app. Package:

```text
dataworks-agent-<version>-windows-x64.zip
dataworks-agent-<version>-linux-x64.tar.gz
SHA256SUMS
sbom.spdx.json
THIRD_PARTY_LICENSES.txt
```

Bundle a sidecar bootstrap that uses uv’s locked environment; do not bundle credentials or local data. Verify each artifact in a clean Windows Sandbox/container.

- [ ] **Step 6: Configure release-please and release workflow**

Release workflow triggers from a signed tag/release PR, runs full dry-run acceptance, requires staging Environment approval, builds artifacts, generates SBOM/checksums, and publishes only after all pass. Conventional squash commit drives changelog. Never publish directly from a feature branch.

- [ ] **Step 7: Rehearse an upstream sync**

```bash
git switch -c upstream-sync
git fetch upstream dev
git merge --no-ff upstream/dev
bun install --frozen-lockfile
bun run verify:upstream
bun run acceptance:dry-run
```

Update `upstream-baseline.json` only after full verification and human review. Record every conflict and whether the local patch can move into a new package/plugin.

- [ ] **Step 8: Complete threat model and operations docs**

Threat model covers: browser session theft, CSRF, worker breakout, path traversal/symlink/junction, plugin prompt injection, malicious documents, secret/log leakage, MCP endpoint abuse, write-ticket replay, staging credential misuse, sidecar protocol abuse, and backup exposure. Backup docs state that `secrets.dat` without the OS keyring entry is not independently restorable; provide an export flow that requires reauthentication and creates a passphrase-encrypted archive.

- [ ] **Step 9: Run final verification matrix**

```bash
bun run lint
bun run --cwd packages/core typecheck
bun run --cwd packages/opencode typecheck
bun run --cwd packages/dataworks-core typecheck
bun run --cwd packages/dataworks-control typecheck
bun run --cwd packages/dataworks-plugin typecheck
bun run --cwd packages/app typecheck
bun run --cwd packages/opencode test:httpapi
bun run acceptance:dry-run
bun run acceptance:staging
```

Expected: every command exits 0. If staging is unavailable, release is blocked; it is not marked skipped/passed.

- [ ] **Step 10: Commit final release infrastructure**

```bash
git add .github scripts tests docs README.md .env.example package.json release-please-config.json .release-please-manifest.json
git commit -m "chore(release): add verified distribution pipeline"
```

**Real acceptance:** a clean machine installs the artifact, creates an admin, logs in, creates a DataConnection, starts an isolated worker, performs real read-only DataWorks/ODPS operations, completes an Agent tool loop, uploads/retrieves a document, and produces auditable evidence.

---

## Dependency and Milestone Summary

| Milestone | Tasks | Depends on | Exit gate |
|---|---:|---|---|
| M0 Fork/Governance | 1–2 | — | pinned upstream imports, typechecks, PR CI dry-run |
| M1 Auth/Isolation/LLM | 3–6 | M0 | authenticated users, encrypted credentials, OCI workers, credential-free streamed model turn |
| M2 Data Plane | 7–9 | M1 | OpenAPI + PyODPS + MCP dry-run/staging adapters, audited writes |
| M3 Agent Tools | 10–11 | M2 | actual OpenCode Session invokes tools; writes/path access gated |
| M4 Web | 12 | M3 | end-user browser flow passes light/dark/mobile/a11y E2E |
| M5 Skill/RAG | 13–14 | M1–M4 | user-isolated Skills/documents/retrieval and provider-scoped egress |
| M6 Release | 15 | all | staging acceptance, failure drills, clean-machine artifacts |

## Suggested Delivery Cadence

- M0: 2–3 engineering days.
- M1: 8–12 engineering days (auth, credential storage, OCI worker isolation, and LLM gateway).
- M2: 7–10 engineering days including Alibaba staging access.
- M3: 4–6 engineering days.
- M4: 5–8 engineering days.
- M5: 7–10 engineering days.
- M6: 5–8 engineering days.

These are sequencing estimates, not commitments. External staging credentials, DataWorks API permissions, and Windows/Linux packaging environments are critical-path prerequisites.

## Definition of Done

- Every task’s code, test, docs, and commit step completed.
- No unfinished markers, sample secrets, copied private fixtures, or disabled required tests remain.
- OpenCode upstream license/notice preserved and local fork patches documented.
- All PRs pass required CI and carry reviewer-verifiable reproduction evidence.
- All DataWorks read paths pass real staging integration; enabled write paths pass a dedicated least-privilege staging write test.
- Two-user isolation tests prove no cross-user sessions, files, workers, credentials, Skills, documents, vectors, or audit records.
- Clean Windows and Linux packages pass startup and full dry-run acceptance.

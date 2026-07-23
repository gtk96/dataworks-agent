# Staging operations

## Purpose

Staging is the **release gate**. Dry-run acceptance can pass without cloud access; staging must exercise real DataWorks OpenAPI and MaxCompute (PyODPS) with dedicated least-privilege credentials.

## Environment

| Variable | Required | Notes |
|---|---|---|
| `DATAWORKS_AGENT_ENV=staging` | yes | Product mode |
| `DATAWORKS_AGENT_DRY_RUN=0` | yes | Must be off |
| `DATAWORKS_AGENT_MODE=staging` | yes | OpenAPI live mode |
| `DATAWORKS_STAGING_AK` / `DATAWORKS_STAGING_SK` | yes | DataWorks OpenAPI |
| `DATAWORKS_STAGING_REGION` | no | Default `cn-hangzhou` |
| `DATAWORKS_STAGING_PROJECT_ID` | yes | Numeric project id |
| `DATAWORKS_STAGING_JOB_INSTANCE_ID` | for job status tests | Numeric instance |
| `DATAWORKS_ODPS_STAGING_AK` / `SK` | yes | MaxCompute |
| `DATAWORKS_ODPS_STAGING_ENDPOINT` | yes | ODPS endpoint |
| `DATAWORKS_ODPS_STAGING_PROJECT` | yes | ODPS project |
| `DWA_STAGING_WRITE_TEST=1` | optional | Enables write-tool drills |
| `DWA_STAGING_LLM_BASE_URL` / `DWA_STAGING_LLM_API_KEY` / `DWA_STAGING_LLM_MODEL` | for session tools | When set, agent-e2e proves `dw_describe_table` + `dw_run_sql` backends; required for `releaseStagingGateComplete` |

## Commands

```bash
# Release gate only (real staging). Windows-safe: env injected inside scripts/acceptance.ts
bun run acceptance:staging

# Optional offline suite — NOT a release gate
bun run acceptance:dry-run
```

- `DATAWORKS_AGENT_DRY_RUN=1 bun scripts/acceptance.ts staging` → **exit 2** (product mode).
- Missing staging secrets → **non-zero hard fail** (never skip-as-pass).

On Windows do **not** rely on `VAR=value bun ...` prefixes; the acceptance script sets env in-process.

## Acceptance flow (public APIs)

1. Login; cross-origin POST/WebSocket rejected (CSRF/origin).
2. Select staging DataConnection (encrypted at rest).
3. List projects/tables.
4. Bounded `SELECT 1` via PyODPS sidecar.
5. OpenCode Session tool loop (`dw_describe_table`, `dw_run_sql`).
6. Write tools:
   - If `DWA_STAGING_WRITE_TEST=1`: rerun no-op job, one-day supplement, pause/restore schedule, silence/restore alert; assert final state equals initial; audit contains reason.
   - If disabled: **every write tool remains blocked** and the release staging gate is **not** complete.
7. Knowledge upload/search with packaged local embedding model.
8. Audit: no prompt/row/secret content in logs or artifacts.

## Artifacts

Staging evidence lands under `artifacts/acceptance/staging/` with timestamps, masked project/instance ids, durations, and screenshots when browser E2E runs. **Never** capture business row contents or secrets.

## Embedding model (MLE5) integrity

Knowledge upload/search in **staging and release** uses the packaged offline MLE5 embedder. The manifest at `packages/dataworks-control/assets/embeddings/manifest.json` must contain a **real** `archiveSha256` (never `PENDING`).

### Operator: fill manifest once (network required)

Archive is ~1.3 GB. Run from repo root when network and disk allow:

```bash
# Windows example
BUN=C:/Users/Administrator/.bun/bin/bun.exe
cd /path/to/dataworks_agent
$BUN scripts/fetch-embedding-model.ts
```

The script:

1. Downloads only the allowlisted FastEmbed `fast-multilingual-e5-large.tar.gz` URL.
2. Computes archive SHA-256 and extracts under `packages/dataworks-control/assets/embeddings/`.
3. Writes `archiveSha256` + per-file digests into `manifest.json`.

**Release gate:** do not ship or accept staging product mode while `archiveSha256` is `PENDING` or empty. `createEmbedder` is **fail-closed**: outside dry-run / explicit hash mode it throws `EmbeddingManifestError` instead of silently using the deterministic hash embedder.

| Mode | Env | Behavior when manifest is PENDING |
|---|---|---|
| Product / staging MLE5 | default or `DWA_EMBEDDING_MODE=mle5` | **Refuse** (`EmbeddingManifestError`) |
| Explicit hash (tests only) | `DWA_EMBEDDING_MODE=hash` | Hash embedder allowed |
| Dry-run acceptance | `DATAWORKS_AGENT_DRY_RUN=1` | Hash embedder allowed |
| Forced hash option | `createEmbedder({ forceHash: true })` | Hash embedder allowed |

Dry-run acceptance may use hash embeddings; staging knowledge steps require a real SHA and extracted model assets.

## Failure policy

Missing secrets → **hard fail** with a clear message. Never skip-as-pass. CI `release.yml` requires the `dataworks-staging` Environment approval before publish. Missing / PENDING embedding `archiveSha256` → **hard fail** for product/staging MLE5 paths (never silent hash fallback).

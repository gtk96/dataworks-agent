# OSS external-table pipeline migration

## Goal

Replace every OSS direct-load path with an external-table-based flow:

```text
OSS source → giikin_develop external table (reuse or create)
           → giikin ODS partition pre-create
           → ODS INSERT OVERWRITE ... SELECT
           → giikin DWD INSERT OVERWRITE ... SELECT
```

No production code or generated SQL may emit `LOAD OVERWRITE` or direct `FROM LOCATION` ingestion.

## Boundaries

- External tables live in project `giikin_develop`.
- ODS and DWD targets live in project `giikin`.
- ODS names are `ods_mc_ads_data__<source>_day` or `_hour`.
- Daily ODS uses `dt='${bizdate}'`; hourly ODS uses `dt='${gmtdate}', ht='${hour_last1h}'`.
- ODS partitions are pre-created with `ADD IF NOT EXISTS PARTITION`.
- DWD partitions are not pre-created by this OSS flow.
- Existing managed external tables are reused only after LOCATION/schema/format compatibility checks; missing tables are created from a bounded schema.
- Standard TikTok material-report flow remains hourly-only.
- ODS nodes retain root dependency; DWD nodes receive the ODS `Normal` dependency and `CrossCycleDependsOnSelf`.
- DWD root-word validation is a hard gate before DDL/node creation.
- Outputs contain only actual ODS/DWD outputs; template-only references are not emitted as runtime outputs.

## Implementation shape

Extend the existing OSS configuration helpers and `OssImportPipeline` rather than retaining a legacy direct-load pipeline. Add focused helpers for:

1. safe external-table naming and DDL generation;
2. managed external-table compatibility/reuse and creation;
3. ODS partition + external-table SELECT SQL;
4. shared day/hour schedule and dependency metadata.

Keep the existing DataWorks node/schedule/publish orchestration and batch persistence interfaces where possible.

## Failure behavior

- Invalid source path, format, schedule, table identifier, or missing root context fails before node creation.
- Missing schema or unresolved external partition mapping returns `needs_context`; do not guess.
- Incompatible existing external table fails explicitly; never silently overwrite it.
- Root-word validation failure prevents DWD artifacts, table creation, node creation, and scheduling.
- Partial node creation reports the node identity and failed step for manual repair.

## Verification

Add unit/integration coverage for day/hour SQL, external-table reuse/create/compatibility, partition pre-creation ordering, no-LOAD invariant, root dependency, DWD validation blocking, ODS dependency persistence, and output minimization. Run affected pytest tests, compileall, ruff, and a repository-wide search for forbidden direct-load SQL in production sources and generated fixtures.

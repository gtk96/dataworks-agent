# OSS External-Table Pipeline Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every OSS direct-load path with a `giikin_develop` external-table → `giikin` ODS → `giikin` DWD pipeline, with day/hour partition correctness, dependency guards, and no generated `LOAD`/direct `FROM LOCATION` SQL.

**Architecture:** Keep the existing `OssImportPipeline` node/schedule/batch orchestration, but replace its SQL producer with focused external-table and ODS SQL helpers. The external-table manager resolves a managed table from Cookie/BFF, validates compatibility, or creates a safe table in `giikin_develop`; the ODS builder emits partition pre-creation followed by `INSERT OVERWRITE ... SELECT`; DWD remains a separate `INSERT OVERWRITE` artifact path. Existing ordinary OSS API callers are migrated to the same pipeline contract rather than retaining a legacy direct-load branch.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest/pytest-asyncio, DataWorks Cookie/BFF and OpenAPI adapters, MaxCompute SQL, Vue 3 frontend where request/response contracts change.

## Global Constraints

- External tables are created/reused in project `giikin_develop`.
- ODS and DWD targets are in project `giikin`.
- ODS names are `ods_mc_ads_data__<source>_day` or `ods_mc_ads_data__<source>_hour`.
- Daily ODS uses partition `dt='${bizdate}'`; hourly ODS uses `dt='${gmtdate}', ht='${hour_last1h}'`.
- ODS runs `ALTER TABLE ... ADD IF NOT EXISTS PARTITION` before `INSERT OVERWRITE ... SELECT`.
- DWD is not pre-created by this OSS flow.
- No production code or generated SQL may emit `LOAD OVERWRITE` or direct `FROM LOCATION` ingestion.
- Existing external tables are reused only after LOCATION, format, schema, and partition compatibility checks.
- Missing external tables are created only from bounded, validated schema information.
- Standard TikTok material-report flow accepts hourly granularity only.
- ODS nodes retain root dependency; DWD nodes include ODS `Normal` dependency and `CrossCycleDependsOnSelf`.
- DWD root-word validation is a hard gate before DDL, table, node, schedule, or publish operations.
- Runtime outputs contain only actual ODS/DWD outputs; template-only parent references are not runtime outputs.
- Do not create or delete DataWorks directories automatically; directory existence must be proven by the existing guard.

---

### Task 1: Add external-table and ODS SQL contracts

**Files:**
- Modify: `dataworks_agent/services/ods_oss/config.py:8-176`
- Create: `dataworks_agent/services/ods_oss/external_table.py`
- Test: `tests/unit/test_ods_oss_config.py`
- Create: `tests/unit/test_ods_oss_external_table.py`

**Interfaces:**
- `external_table.py` produces `ExternalTableSpec`, `build_external_table_ddl()`, and `validate_external_table_compatibility()`.
- `config.py` produces `build_ods_extract_sql(source_table, target_table, granularity, source_project="giikin_develop", target_project="giikin", source_partition="pt", source_partition_value=None)` and `ods_table_name(source_name, granularity)`.
- `build_ods_extract_sql()` must reject an absent `source_partition_value` when the external table is partitioned; it must never guess a `pt` value.

- [ ] **Step 1: Write failing tests for naming and SQL order**

```python
def test_ods_table_name_and_hour_sql():
    assert ods_table_name("tiktok_ad_insights", "hour") == (
        "ods_mc_ads_data__tiktok_ad_insights_hour"
    )
    sql = build_ods_extract_sql(
        source_table="tiktok_ad_insights",
        target_table="ods_mc_ads_data__tiktok_ad_insights_hour",
        granularity="hour",
        source_partition_value="2026071412",
    )
    assert sql.index("ADD IF NOT EXISTS PARTITION") < sql.index("INSERT OVERWRITE")
    assert "giikin.ods_mc_ads_data__tiktok_ad_insights_hour" in sql
    assert "giikin_develop.tiktok_ad_insights" in sql
    assert "dt='${gmtdate}'" in sql and "ht='${hour_last1h}'" in sql
    assert "LOAD OVERWRITE" not in sql and "FROM LOCATION" not in sql


def test_daily_ods_sql_uses_only_daily_partition():
    sql = build_ods_extract_sql(
        source_table="tiktok_ad_struct",
        target_table="ods_mc_ads_data__tiktok_ad_struct_day",
        granularity="day",
        source_partition_value="20260713",
    )
    assert "dt='${bizdate}'" in sql
    assert "ht=" not in sql
    assert "${gmtdate}" not in sql


def test_missing_external_partition_value_needs_context():
    with pytest.raises(ValueError, match="source_partition_value"):
        build_ods_extract_sql(
            source_table="source",
            target_table="ods_mc_ads_data__source_hour",
            granularity="hour",
        )
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run python -m pytest tests/unit/test_ods_oss_config.py tests/unit/test_ods_oss_external_table.py -q --tb=short`

Expected: FAIL because the new helpers are not defined and the old builder still emits `LOAD OVERWRITE`.

- [ ] **Step 3: Implement bounded identifier, DDL, compatibility, and ODS SQL helpers**

Implement the following shape:

```python
@dataclass(frozen=True)
class ExternalTableSpec:
    project: str
    table: str
    columns: tuple[tuple[str, str], ...]
    partition_columns: tuple[str, ...]
    file_format: str
    location: str


def ods_table_name(source_name: str, granularity: Literal["day", "hour"]) -> str:
    safe = safe_source_identifier(source_name)
    return f"ods_mc_ads_data__{safe}_{granularity}"


def build_external_table_ddl(spec: ExternalTableSpec) -> str:
    # Emit CREATE EXTERNAL TABLE IF NOT EXISTS with escaped literals and
    # explicit columns/partition/storage; never emit an ODS LOAD statement.
    ...


def validate_external_table_compatibility(spec, observed_ddl) -> list[str]:
    # Compare project/table identity, normalized LOCATION, file format,
    # columns, and partition columns; return actionable errors.
    ...

def build_ods_extract_sql(...):
    # Emit ALTER TABLE giikin.<ods> ADD IF NOT EXISTS PARTITION first,
    # then INSERT OVERWRITE TABLE giikin.<ods> PARTITION ... SELECT ...
    # FROM giikin_develop.<external>; qualify every identifier safely.
    ...
```

The implementation must use the existing `parse_oss_path`, identifier validation, and SQL literal escaping conventions instead of duplicating unsafe string checks.

- [ ] **Step 4: Run focused tests and formatting**

Run: `uv run python -m pytest tests/unit/test_ods_oss_config.py tests/unit/test_ods_oss_external_table.py -q --tb=short` and `uv run ruff check dataworks_agent/services/ods_oss/config.py dataworks_agent/services/ods_oss/external_table.py tests/unit/test_ods_oss_config.py tests/unit/test_ods_oss_external_table.py`

Expected: PASS with no lint errors.

---

### Task 2: Replace the OSS pipeline direct-load path

**Files:**
- Modify: `dataworks_agent/services/ods_oss/pipeline.py`
- Modify: `dataworks_agent/routers/pipeline.py`
- Modify: `dataworks_agent/services/ods_oss/managed_discovery.py`
- Modify: `dataworks_agent/api_clients/bff_client.py` only where an existing metadata/DDL method is reused
- Test: `tests/unit/test_ods_oss_pipeline.py`
- Test: `tests/unit/test_ods_oss_managed_discovery.py`
- Test: `tests/integration/test_pipeline_api.py`

**Interfaces:**
- `OssImportPipeline.run()` returns steps `validate`, `resolve_external_table`, `build_sql`, `create_node`, `configure_schedule`, `configure_dependencies`, and `publish`.
- `resolve_external_table` returns `{project, table_name, source_partition, metadata_source, created}`.
- The pipeline must call the existing BFF/OpenAPI-compatible SQL execution abstraction for external-table creation, not a raw HTTP call.

- [ ] **Step 1: Write failing tests for reuse/create and no-LOAD behavior**

```python
@pytest.mark.asyncio
async def test_pipeline_reuses_compatible_managed_external_table(monkeypatch):
    client = FakeBff(managed_external_table={
        "table_name": "source",
        "project": "giikin_develop",
        "columns": [{"name": "json_data", "type": "STRING"}],
        "partition_columns": ["pt"],
        "location": "oss://bucket/source/",
    })
    result = await OssImportPipeline(client).run(
        oss_path="oss://bucket/source/",
        target_table="ods_mc_ads_data__source_hour",
        file_format="json",
        schedule_type="hour",
        source_partition_value="2026071412",
        publish=False,
    )
    assert result["success"] is True
    assert result["steps"]["resolve_external_table"]["created"] is False
    assert "LOAD OVERWRITE" not in result["sql"]
    assert "FROM LOCATION" not in result["sql"]

@pytest.mark.asyncio
async def test_pipeline_creates_missing_external_table(monkeypatch):
    client = FakeBff(managed_external_table=None)
    result = await OssImportPipeline(client).run(
        oss_path="oss://bucket/source/",
        target_table="ods_mc_ads_data__source_day",
        file_format="json",
        schedule_type="day",
        source_partition_value="20260713",
        publish=False,
    )
    assert result["success"] is True
    assert result["steps"]["resolve_external_table"]["created"] is True
    assert client.executed_sql[0].startswith("CREATE EXTERNAL TABLE")
```

- [ ] **Step 2: Run focused pipeline tests and verify failure**

Run: `uv run python -m pytest tests/unit/test_ods_oss_pipeline.py tests/unit/test_ods_oss_managed_discovery.py -q --tb=short`

Expected: FAIL because the current pipeline calls `build_oss_import_sql()` and has no external-table resolution step.

- [ ] **Step 3: Implement external-table resolution and pipeline SQL migration**

Add a small adapter in the pipeline that:

1. derives source name from the canonical parsed OSS path;
2. invokes managed discovery and preserves the actual `table_name`, `entity_guid`, columns, partition columns, format, and LOCATION;
3. validates an existing table before reuse;
4. creates the external table through the configured SQL execution client when absent;
5. returns `needs_context` when schema or `pt` value is unavailable;
6. builds only ODS `ALTER` + `INSERT` SQL;
7. leaves node/schedule/root dependency orchestration intact;
8. emits only the ODS output reference.

Replace the current `build_oss_import_sql` import and call. Remove the old builder after all callers are migrated. Validate `schedule_type` strictly as `day` or `hour`; never silently treat typos as daily.

- [ ] **Step 4: Preserve dependency persistence and remove redundant outputs**

Keep the existing inline dependency path for BFF/OpenAPI. Set the ODS dependency output to `giikin.<ods_table>` and use `Normal` for the configured root plus `CrossCycleDependsOnSelf` for the ODS node. Do not return template-only parent references as runtime outputs.

- [ ] **Step 5: Run focused tests and integration contract tests**

Run: `uv run python -m pytest tests/unit/test_ods_oss_pipeline.py tests/unit/test_ods_oss_managed_discovery.py tests/integration/test_pipeline_api.py -q --tb=short`

Expected: PASS; any tests that still assert `LOAD OVERWRITE` must be rewritten to assert `ALTER` then `INSERT` and no forbidden tokens.

---

### Task 3: Align managed discovery result contracts

**Files:**
- Modify: `dataworks_agent/services/ods_oss/managed_discovery.py`
- Modify: `dataworks_agent/services/ods_oss/schema_discovery.py` only if the shared source-name/format helper is required
- Test: `tests/unit/test_ods_oss_managed_discovery.py`

**Interfaces:**
- Successful managed discovery always includes `table_name`, `project`, `entity_guid`, `location`, `columns`, `partition_columns`, `file_format`, and `ingestion_mode`.
- `inspect_oss_directory_with_cookie()` uses the actual managed `table_name`; it must not fall back to an OSS basename when a match exists.

- [ ] **Step 1: Add failing identity and compatibility tests**

```python
def test_managed_success_preserves_case_and_real_table_name():
    result = discover_managed_oss_schema(...)
    assert result["table_name"] == "REPORT"
    directory = inspect_oss_directory_with_cookie(...)
    assert directory["directory_check"]["matched_external_table"] == "REPORT"


def test_managed_result_exposes_partition_columns():
    result = discover_managed_oss_schema(...)
    assert result["partition_columns"] == ["pt"]
```

- [ ] **Step 2: Implement result propagation**

Capture the selected table record once, propagate its real name and partition columns into the success payload, and build directory-check entries from the actual managed registration rather than a path-derived basename.

- [ ] **Step 3: Run tests and lint**

Run: `uv run python -m pytest tests/unit/test_ods_oss_managed_discovery.py -q --tb=short` and `uv run ruff check dataworks_agent/services/ods_oss/managed_discovery.py tests/unit/test_ods_oss_managed_discovery.py`

Expected: PASS.

---

### Task 4: Make standard Material Report hourly and use giikin project boundaries

**Files:**
- Modify: `dataworks_agent/modeling/standard_oss.py`
- Modify: `dataworks_agent/agent/workflow_service.py` at standard OSS profile/pipeline call sites
- Test: `tests/unit/test_standard_oss_workflow.py`
- Test: `tests/unit/test_agent_ods_dwd.py`

**Interfaces:**
- `build_standard_material_report_ods_artifacts()` emits `giikin` ODS DDL/SQL and external-table-based ODS extraction.
- `build_standard_material_report_artifacts(granularity="day")` raises a clear `ValueError` before DDL/SQL generation.
- Standard DWD SQL reads `giikin.<ods_table>` and writes `giikin.<dwd_table>`.
- `logical_primary_keys` must be a subset of mapped DWD target fields.

- [ ] **Step 1: Add failing tests**

```python
def test_standard_material_report_rejects_daily_granularity():
    with pytest.raises(ValueError, match="hourly"):
        build_standard_material_report_artifacts(
            field_mappings=[{"json_key": "id", "target_name": "id"}],
            granularity="day",
            logical_primary_keys=["id"],
        )


def test_standard_dwd_rejects_unknown_logical_key():
    with pytest.raises(ValueError, match="not_a_field"):
        build_standard_material_report_artifacts(
            field_mappings=[{"json_key": "id", "target_name": "id"}],
            logical_primary_keys=["not_a_field"],
        )


def test_standard_artifacts_use_requested_schedule_minute():
    artifacts = build_standard_material_report_artifacts(
        field_mappings=[{"json_key": "id", "target_name": "id"}],
        logical_primary_keys=["id"],
        schedule_minute=15,
    )
    assert " 15 " in artifacts["schedule"]["cron"]
```

- [ ] **Step 2: Implement fixed-hour and project-qualified standard artifacts**

Reject `granularity != "hour"` in the standard builder. Set `ODS_PROJECT = "giikin"` and use the external source project separately. Build standard ODS SQL as `ALTER` + `INSERT` from the real managed external table. Build DWD SQL with `giikin.<ods_table>` source and `giikin.<dwd_table>` target. Validate logical keys against `{mapping.target_name for mapping in mappings}` before constructing metadata.

- [ ] **Step 3: Make RootChecker a hard gate**

After `RootChecker().check_fields_local(...)`, raise/return a blocking validation result before DDL/node creation when `passed` is false. Preserve the result in error data so callers can display the failed fields.

- [ ] **Step 4: Remove template-only runtime outputs**

Keep only the actual ODS and DWD table outputs in dependency payloads/artifacts. Preserve template IDs only as provenance metadata, not as runtime `outputs` or active parent dependencies.

- [ ] **Step 5: Run standard workflow tests**

Run: `uv run python -m pytest tests/unit/test_standard_oss_workflow.py tests/unit/test_agent_ods_dwd.py -q --tb=short`

Expected: PASS, including hourly SQL, rejection of daily standard flow, logical-key blocking, requested-minute cron, root validation, and ODS dependency assertions.

---

### Task 5: Migrate API/frontend contracts and documentation

**Files:**
- Modify: `dataworks_agent/routers/pipeline.py`
- Modify: `frontend/src/pages/DataIntegration.vue`
- Modify: `frontend/src/pages/PipelineHub.vue`
- Modify: `docs/product/any-oss-source-plan.md`
- Modify: `README.md` only where direct-load behavior is documented
- Test: `tests/integration/test_pipeline_api.py`
- Test: frontend unit/E2E fixtures that assert OSS SQL or pipeline payloads

**Interfaces:**
- OSS submission accepts source partition context when the external table is partitioned.
- API responses expose external-table resolution and ODS extraction steps without exposing credentials or sample content.
- UI displays `needs_context` for missing `pt` mapping instead of submitting a guessed SQL.

- [ ] **Step 1: Add API contract tests**

Assert valid day/hour requests return strict success, include `resolve_external_table`, and return SQL without `LOAD OVERWRITE` or direct `FROM LOCATION`. Assert missing source partition context returns a controlled `needs_context` response rather than 500.

- [ ] **Step 2: Update request models and route forwarding**

Add a nullable `source_partition_value`/equivalent field to the OSS submission model, validate it before enqueueing, and pass it to `OssImportPipeline.run()`. Preserve `submissions` as the batch field and keep idempotency behavior.

- [ ] **Step 3: Update UI forms and status display**

Add the partition value/context field or show a blocking clarification when the selected external table has `pt` and no mapping is supplied. Replace wording that promises direct OSS loading with external-table extraction wording. Display external table name, metadata source, ODS target, and step errors.

- [ ] **Step 4: Synchronize product documentation**

Document project boundaries (`giikin_develop` source, `giikin` ODS/DWD), day/hour naming and parameters, external-table reuse/create, ODS partition pre-creation, DWD dependency/root-word gates, and the removal of direct-load SQL. Remove stale claims that the generic OSS path uses `LOAD OVERWRITE`.

- [ ] **Step 5: Run API and frontend checks**

Run: `uv run python -m pytest tests/integration/test_pipeline_api.py -q --tb=short`; from `frontend`, run `npm run test:unit` and `npm run build`.

Expected: PASS; UI does not expose a direct-load action and API payloads match the new contract.

---

### Task 6: Repository-wide forbidden SQL and regression verification

**Files:**
- Modify: all remaining production/test/docs files found by the searches below
- Test: affected files from the search results

- [ ] **Step 1: Search all tracked and generated sources**

Run:

```bash
rg -n --hidden --glob '!node_modules' --glob '!*.lock' "LOAD OVERWRITE|FROM LOCATION" dataworks_agent tests frontend docs
```

Expected: no production or generated SQL matches. Any test fixture that intentionally documents the forbidden legacy form must be rewritten to the new external-table form or removed.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run python -m compileall -q dataworks_agent
uv run ruff check .
```

Expected: exit code 0.

- [ ] **Step 3: Run the focused OSS suite**

Run:

```bash
uv run python -m pytest \
  tests/unit/test_ods_oss_config.py \
  tests/unit/test_ods_oss_external_table.py \
  tests/unit/test_ods_oss_pipeline.py \
  tests/unit/test_ods_oss_managed_discovery.py \
  tests/unit/test_standard_oss_workflow.py \
  tests/unit/test_agent_ods_dwd.py \
  tests/integration/test_pipeline_api.py \
  -q --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Run the full backend suite**

Run: `uv run python -m pytest -q --tb=short`

Expected: all tests pass; if an unrelated pre-existing failure occurs, record its exact file and failure without masking it.

- [ ] **Step 5: Run frontend verification**

Run from `frontend`:

```bash
npm run test:unit
npm run build
```

Expected: both commands pass.

- [ ] **Step 6: Verify generated artifacts and final diff**

Run:

```bash
rg -n --hidden --glob '!node_modules' "LOAD OVERWRITE|FROM LOCATION" .
git diff --check
git status --short
```

Expected: forbidden SQL appears nowhere in source, tests, docs, or generated fixtures; diff has no whitespace errors; only intended files are modified.

---

# OSS 数据源全链路实施说明

## 目标链路

所有 OSS 数据源统一使用：

```text
OSS 路径
→ giikin_develop 外部表（已存在则复用并校验，不存在则创建）
→ giikin ODS
→ DWD
```

禁止直接从 OSS `LOCATION` 灌入 ODS。

## ODS 规则

- 表名：`ods_mc_ads_data__<source>_day` 或 `ods_mc_ads_data__<source>_hour`
- 字段：`json_data STRING`
- 存储：`aliorc`
- 日表分区：`dt='${bizdate}'`
- 小时表分区：`dt='${gmtdate}', ht='${hour_last1h}'`
- 执行顺序：先 `ALTER TABLE ... ADD IF NOT EXISTS PARTITION`，再 `INSERT OVERWRITE ... SELECT json_data FROM giikin_develop.<external_table>`

## 外部表规则

- Project：`giikin_develop`
- 已存在外部表必须校验 LOCATION、字段、格式和分区列后才能复用。
- 不存在时使用受限 Schema 创建；无法确认字段或外部 `pt` 分区值时返回 `needs_context`，不猜测。
- 外部表分区 `pt` 与 ODS 的 `dt/ht` 独立。

## DWD 与依赖

- DWD 位于 `giikin`，从 `giikin` ODS 使用 `INSERT OVERWRITE ... SELECT`。
- OSS 流程不预创建 DWD 分区。
- ODS 节点保留 root 依赖和跨周期自依赖。
- DWD 字段必须通过 RootChecker；失败时阻断 DDL、建表、建节点、调度和发布。
- DWD 添加 ODS `Normal` 依赖和 `CrossCycleDependsOnSelf`。
- 运行时 outputs 只保留真实 ODS/DWD 输出，不输出模板遗留引用。

## 标准 Material Report

` tiktok_smart_plus_material_report` 当前固定使用小时粒度和已有 `_hour` ODS/DWD 表；传入 `day` 时拒绝，不生成半成品 daily 产物。

## 验收

```text
生产代码和生成 SQL 中不得出现 LOAD OVERWRITE 或 FROM LOCATION。
```

验证命令：

```powershell
uv run python -m pytest tests/unit/test_ods_oss_config.py tests/unit/test_ods_oss_external_table.py tests/unit/test_ods_oss_pipeline.py tests/unit/test_ods_oss_managed_discovery.py tests/unit/test_standard_oss_workflow.py tests/unit/test_agent_ods_dwd.py tests/integration/test_pipeline_api.py -q --tb=short
uv run ruff check .
uv run python -m compileall -q dataworks_agent
```

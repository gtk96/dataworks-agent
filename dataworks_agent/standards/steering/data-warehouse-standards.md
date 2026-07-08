---
inclusion: fileMatch
fileMatchPattern: "**/*.sql"
description: 数仓建设规范速查：分层架构、表命名、更新方式、字段类型、调度参数
---

# 数仓建设规范速查

> 完整规范见 `reference/standards/`，此处仅保留开发时高频查阅的速查内容。

## 分层架构与引用规则

```
DMR 集市层 ← DWS 汇总层 ← DWD 明细层/DIM 维度层 ← ODS 贴源层 ← 数据源
```

- DMR 只引用 DWS；DWS 引用 DWD/DIM；DWD/DIM 引用 ODS

## 主题域

| 缩写 | 主题域 | 缩写 | 主题域 |
|------|--------|------|--------|
| ord | 订单域 | fin | 账务域 |
| gds | 物品域 | svc | 服务域 |
| evt | 事件域 | mkt | 营销域 |
| scm | 供应链 | pty | 参与人 |
| pub | 公共域 | | |

## 表命名规范

| 层级 | 命名规则 |
|------|---------|
| ODS | `ods_{原库类型}_{原库名}__{原表名}_{更新方式}` |
| DWD | `dwd_{主题域}_{表主体}_{更新方式}` |
| DWS | `dws_{主题}_{表主体}_{更新方式}` |
| DMR | `dmr_{表主体}_{更新方式}` |
| Holo | `hl_{用途}_{域}_{实体}`（不套用数仓分层前缀，放 `cda` schema） |
| 临时表 | `tmp_{结果表名}_{序号}` |

Holo 用途前缀：`hl_rt_`（实时）/ `hl_sv_`（服务）/ `hl_stg_`（中转）/ `hl_dim_`（维度）

## 更新方式后缀

| 后缀 | 含义 | 分区字段 |
|------|------|---------|
| hour | 小时增量 | dt, ht |
| hourly | 小时全量 | dt, ht |
| day | 日增量 | dt |
| all | 日全量 | dt |
| his | 拉链 | begin_dt, end_dt |
| static | 静态表 | 无 |

## 字段类型规则

| 字段类别 | ODPS 类型 | Holo 类型 |
|---------|-----------|-----------|
| 默认（ID、名称、状态等） | `string` | `text` |
| 金额类（amt/cost/price/fee/spend/budget 等） | `decimal(24,6)` | `numeric(24,6)` |
| 可累加数量（cnt/orders/sales/clicks 等） | `bigint` | `bigint` |
| 比率类（ratio/cnv/ctr/roi 等） | `decimal(24,6)` | `numeric(24,6)` |

注意：`id` 结尾字段不是数字类型，用 `string` / `text`

## 调度参数

| 参数 | 格式 | 用途 |
|------|------|------|
| `${bizdate}` | yyyymmdd | 日调度业务日期（昨日） |
| `${biz_date}` | yyyy-mm-dd | 日调度业务日期（昨日） |
| `${gmtdate}` | yyyymmdd | 小时调度业务日期 |
| `${hour_last1h}` | hh | 上一小时 |
| `${hour_last2h}` | hh | 上两小时 |
| `${gmtdate_last2h}` | yyyymmdd | 上两小时对应日期 |

> 昨日日期函数写法（不依赖调度参数）：`date_format(dateadd(to_date('${bizdate}', 'yyyymmdd'), -1, 'dd'), 'yyyyMMdd')`
> ⚠️ 注意：`date_format` 格式串中月份必须用大写 `MM`，小写 `mm` 是分钟，会导致月份输出为 `00`（如 `20260427` → `20260026`）

## 重要约束

1. ODS 为 JSON 格式的表（ODS 只有一个 `json_data` 字段存所有数据），DWD 层必须保留 `json_data` 原始字段（含 Holo 表）；ODS 为多字段结构化表（数据库直接同步），DWD 不加 `json_data`——判断依据是 ODS 表结构，与平台无关
2. Holo 外表只支持 `insert into`，不支持 `insert overwrite` / `delete`
3. Holo 外表字段顺序必须与 MC 表严格一一对应，分区字段放最后
4. Holo 主键必须声明 `not null` + `primary key`
5. JSON key 区分大小写，必须与源数据完全一致
6. DDL 前必须加 `drop table if exists`；临时表过程结束前必须 drop；**建表语句不加 `if not exists`**
7. **DML SELECT 列数必须与 DDL 非分区字段数严格一致**：写完 DML 后必须数列数；`json_data` 固定放 SELECT 最后一列，最容易漏写；漏写会报 `ODPS-0130071: wrong columns count`
8. **多子查询 coalesce 时必须核对别名**：外层引用 `t1.xxx`/`t2.xxx` 的每个字段，必须在对应子查询的 SELECT 别名中真实存在；json_tuple 解析出的原始别名（如 `m_status`、`m_updated_time`）与目标字段名（如 `ad_group_status`、`update_time`）不同时，必须在子查询 SELECT 里显式 `as` 转换，不能在外层直接用目标名引用（详见 PIT-20260508-004）
9. **历史数据补充用 `left anti join`，禁止用 `not in`**：`not in` 遇到子查询返回 NULL 会导致整个结果为空；`left anti join` 无此问题且性能更好；模板见 skill/modeling/dwd-from-ods.md
10. **ODS/DWD/DWS/DMR 表不设 LIFECYCLE**（永久保存）；只有临时表（`tmp_`）才设生命周期

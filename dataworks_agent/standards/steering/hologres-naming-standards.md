---
inclusion: fileMatch
fileMatchPattern: "**/*.sql"
description: Hologres 表命名规范速查：hl_ 前缀体系和用途分类
---

# Hologres 表命名规范速查

> Holo 定位为服务层/加速层，不套用 ODS→DWD→DWS→DMR 分层前缀。

## 命名结构

```
hl_{用途}_{业务域}_{实体描述}_{更新方式后缀}
```

**更新方式后缀规则（V1.0 规范）**：
- ODS/DWD/DIM/DWS 层所有实时更新表：**强制加 `_rt` 后缀**
- DMR 层从 MaxCompute 同步的表：与源表名完全一致，**不加任何后缀**
- DMR 层 Hologres 本地加工生成的表：加 `_rt` 后缀

## 用途前缀

| 前缀 | 含义 | 典型场景 |
|------|------|---------|
| `hl_rt_` | 实时层 | CDC 同步、实时写入 |
| `hl_sv_` | 服务层 | BI/API/报表直接查询 |
| `hl_stg_` | 中转层 | Holo 与 MC 数据中转（含外表） |
| `hl_dim_` | 维度层 | 维度表在 Holo 的副本 |

## Schema 规范

所有 Holo 表统一放在 `cda` schema 下：`cda.hl_sv_mkt_ad_group_info`

## 业务库 Binlog 同步表的命名

业务库通过 Binlog CDC 同步到 Holo 后，根据是否需要"纠正处理"决定命名：

| 场景 | 命名规则 | 示例 |
|------|---------|------|
| 不需要纠正处理 | 直接落原生 schema，表名与源库一致 | `ofc.s_order` / `oms.t_order_ad` / `gimp.gk_order_ad` |
| 需要纠正处理（如标准化字段值） | 落到 `cda.ods_hl_{源schema}__{源表名}_min` | `cda.ods_hl_gimp__gk_order_info_min`（做了 currency_id=7→21、ship_country='UK'→'GB' 标准化） |

**关键判断**：默认走"原生 schema"，**只有当源表数据需要标准化/清洗才走 `cda.ods_hl_xxx`**。下游建模时优先 JOIN 原生 schema 的表，不要假设所有源表都有 `cda.ods_hl_xxx` 镜像。

## 字段类型对应

| ODPS 类型 | Holo 类型 |
|-----------|-----------|
| `string` | `text` |
| `bigint` | `bigint` |
| `decimal(24,6)` | `numeric(24,6)` |

## 命名示例

```
hl_sv_mkt_ad_group_effect_rt     -- 广告组效果（服务层实时快照，强制 _rt）
hl_sv_mkt_ad_acct_info_rt        -- 广告账户信息（服务层实时快照，强制 _rt）
hl_stg_mkt_ad_group_info_hour    -- 中转外表（映射 MC 小时增量表）
hl_rt_ord_gk_order_info_min      -- 订单实时层（5分钟粒度）
hl_dim_gds_site_info_rt          -- 站点维度副本（实时更新，加 _rt）
dmr_ord_order_analysis_day       -- 从 MC 同步的 DMR 表（与源表名完全一致，不加后缀）
```

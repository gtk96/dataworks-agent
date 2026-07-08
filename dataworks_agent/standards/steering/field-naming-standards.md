---
inclusion: fileMatch
fileMatchPattern: "**/*.sql"
description: 字段命名词根规范速查：常见易错点和禁止行为
---

# 字段命名词根规范速查

> 完整词根表查询：`select * from dataworks.dim_pub_column_dictionary_static limit 500`
> 详细规范见 `reference/standards/`

## 核心规则

- 字段名按 `_` 拆分后，每个片段必须在词根表 `column_name` 列中**精确匹配**
- 禁止凭直觉判断，禁止虚构词根
- `id` 不能单独使用，必须加业务前缀（如 `order_id`）
- 全小写，下划线分隔

## 常见非法词根

| 非法用法 | 原因 | 正确替换 |
|---------|------|---------|
| `created_by` / `updated_by` | `by` 不在词根表 | `create_user_id` / `update_user_id` |
| `creator` / `creater` | 不在词根表 | `create_user_name` / `create_user_id` |
| `account` | 不在词根表 | `acct` |
| `customer` | 不在词根表 | `cust` |
| `number` | 不在词根表 | `no` |
| `count` | 不在词根表 | `cnt` |
| `amount` | 不在词根表 | `amt` |
| `advertiser` | 不在词根表 | `ad_acct` |
| `lifetime` | 不在词根表 | `total`（如 lifetime_budget→total_budget） |
| `optimizer` | 不在词根表 | `opt` |
| `lang` | 不在词根表 | `language` |
| `route` / `channel` | 不在词根表 | `chnl` |
| `onsite` | 不在词根表 | `site` |
| `shopping` | 不在词根表 | `pay`（如 onsite_shopping→site_pay_cnt） |
| `execute` / `exec` | 不在词根表 | `rule`/`run`（如 execute_log→rule_log） |
| `cal` / `calc` / `compute` | 不在词根表 | `process`/`etl`（如 cal_time→process_time） |
| `on`（单独片段） | 不在词根表 | 去掉或改写（如 on_web→web） |
| 单独的 `id` | 规定不能单独使用 | 加业务前缀 |

## 广告域常用映射

| 原始字段 | 标准词根 |
|---------|---------|
| adset / ad_group | ad_group |
| account / ad_account | ad_acct |
| campaign | ad_campaign |
| bid_amount | bid_amt |
| spend | spend_amt |
| impressions | pv |
| conversions | cnv |

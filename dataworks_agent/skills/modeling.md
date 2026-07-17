---
name: modeling
description: 全链路数仓建模：ODS→DWD→DIM→DWS 分层建表、SQL 生成、调度配置
triggers: ["建模", "建表", "create", "ods", "dwd", "dim", "dws", "forward_modeling", "reverse_modeling"]
tools: [create_table, generate_ddl, generate_dml, create_node, configure_schedule]
priority: 8
category: modeling
---
# 建模 Skill

全链路数仓建模能力。

## 触发条件
用户提到建表、建模、ODS/DWD/DIM/DWS 分层、正向/逆向建模。

## 可用工具
- create_table: 创建数据表
- generate_ddl: 生成 DDL 语句
- generate_dml: 生成 DML 语句
- create_node: 创建 DataWorks 节点
- configure_schedule: 配置调度参数

## 示例
用户: "帮我建一张 DWD 订单明细表"
→ 匹配 modeling Skill
→ 调用 generate_ddl + create_node

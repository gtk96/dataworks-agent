---
name: governance
description: 数仓治理：词根校验、命名规范、DDL 检查、血缘管理
triggers: ["治理", "词根", "规范", "命名", "governance", "校验", "DDL 检查", "血缘"]
tools: [check_ddl, check_word_root, get_lineage, get_bus_matrix]
priority: 6
category: governance
---
# 治理 Skill

数仓规范和治理。

## 触发条件
用户提到词根、命名规范、DDL 检查、血缘、总线矩阵。

## 可用工具
- check_ddl: 检查 DDL 规范性
- check_word_root: 校验词根合规
- get_lineage: 获取血缘
- get_bus_matrix: 获取总线矩阵

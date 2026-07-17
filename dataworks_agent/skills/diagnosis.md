---
name: diagnosis
description: 异常排查：任务失败诊断、血缘影响面分析、根因定位
triggers: ["诊断", "排查", "失败", "异常", "diagnose", "报错", "为什么失败", "影响范围", "根因"]
tools: [diagnose_task, get_lineage, get_upstream_tasks, query_logs]
priority: 7
category: diagnosis
---
# 诊断 Skill

任务异常排查和根因分析。

## 触发条件
用户提到任务失败、报错、异常、排查、影响范围。

## 可用工具
- diagnose_task: 诊断任务失败原因
- get_lineage: 获取血缘关系
- get_upstream_tasks: 获取上游任务
- query_logs: 查询执行日志

## 示例
用户: "昨天那个订单任务为什么失败了？"
→ 匹配 diagnosis Skill
→ 调用 diagnose_task → get_lineage

---
name: query
description: 智能问数：自然语言查询指标，自动解析口径、生成 SQL、返回图表
triggers: ["查询", "指标", "GMV", "订单量", "ask_data", "query", "看数据", "统计"]
tools: [query_metric, generate_chart, clarify_caliber, execute_query]
priority: 7
category: query
---
# 问数 Skill

通过自然语言查询数仓指标。

## 触发条件
用户询问指标值、数据趋势、对比分析、统计查询。

## 可用工具
- query_metric: 查询指标值
- generate_chart: 生成图表
- clarify_caliber: 口径澄清
- execute_query: 执行查询

## 示例
用户: "昨天 GMV 是多少？"
→ 匹配 query Skill
→ 调用 clarify_caliber → query_metric → generate_chart

"""意图模板定义。"""

from __future__ import annotations

from typing import Any

INTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "publish_review": {
        "patterns": [
            r"(直接)?发布.*?(表|节点|任务|dwd|ods|dim|dws|dmr)",
            r"(上线|提交).*?(审批|发布|publish|gate)",
            r"publish.*?(review|check|gate|risk)",
        ],
        "required_params": [],
        "optional_params": ["goal", "table_name", "source_table", "layer"],
    },
    "metric_attribution": {
        "patterns": [
            r"(指标|口径|metric).*?(下降|波动|异常|归因|为什么|原因)",
            r"(为什么|原因).*?(指标|口径|转化率|gmv|销售额|订单量)",
            r"attribution|root cause",
        ],
        "required_params": [],
        "optional_params": ["goal", "metric_id", "table_name"],
    },
    "diagnose_issue": {
        "patterns": [
            r"(排查|诊断|修复|自愈).*?(失败|异常|报错|任务|调度|数据)",
            r"(任务|调度|节点).*?(失败|异常|报错|恢复)",
            r"(self[-_ ]?heal|diagnose|troubleshoot)",
        ],
        "required_params": [],
        "optional_params": ["goal", "task_id", "table_name"],
    },
    "reverse_modeling": {
        "patterns": [
            r"(逆向|存量).*?(建模|表结构|血缘|语义)",
            r"(分析|梳理).*?(存量表|已有表)",
            r"reverse.*model",
        ],
        "required_params": [],
        "optional_params": ["goal", "table_name", "source_table", "layer"],
    },
    "ods_dwd_modeling": {
        "patterns": [
            r"(ods|\u8d34\u6e90|\u5165\u4ed3).*?(dwd|\u660e\u7ec6)",
            r"(dwd|\u660e\u7ec6).*?(ods|\u8d34\u6e90|\u5165\u4ed3)",
            r"(\u4ece|\u57fa\u4e8e|source).*?(ods).*?(dwd)",
            r"ods\s*(?:\+|and|\u518d|\u5230|->|\u2192).*?dwd",
            r"source.*?ods.*?dwd",
        ],
        "required_params": [],
        "optional_params": [
            "goal",
            "table_name",
            "source_table",
            "layer",
            "domain",
            "schedule_cycle",
            "source_type",
            "datasource_name",
            "oss_path",
            "ods_table",
            "dwd_table",
            "granularity",
            "schedule_minute",
        ],
    },
    "forward_modeling": {
        "patterns": [
            r"(正向|生成|设计|规划).*?(建模|模型|dwd|dws|dim|dmr)",
            r"(帮我|请).*?(建模|生成.*ddl|生成.*dml|设计.*模型)",
            r"(建成|建设|产出).*?(明细|汇总|维度|报表|模型)",
            r"forward.*model",
        ],
        "required_params": [],
        "optional_params": ["goal", "table_name", "source_table", "layer", "domain", "schedule_cycle"],
    },
    "agent_workflow": {
        "patterns": [
            r"agent.*(处理|完成|规划|执行|自动)",
            r"(端到端|全流程|自动).*?(建模|数仓|dataworks|调度|节点)",
            r"帮我.*?(处理|搞定|完成).*?(dataworks|数仓|建模|节点|调度)",
        ],
        "required_params": [],
        "optional_params": ["goal", "table_name", "source_table", "layer", "domain", "schedule_cycle"],
    },
    "create_table": {
        "patterns": [
            r"创建.*表",
            r"新建.*表",
            r"建.*表",
            r"create.*table",
        ],
        "required_params": ["table_name"],
        "optional_params": ["source_table", "layer", "domain", "schedule_cycle", "description"],
    },
    "query_lineage": {
        "patterns": [
            r"查询.*血缘",
            r"查看.*依赖",
            r"影响.*分析",
            r"血缘.*影响",
            r"query.*lineage",
        ],
        "required_params": ["table_name"],
        "optional_params": ["depth", "source_table"],
    },
    "check_status": {
        "patterns": [
            r"检查.*状态",
            r"查看.*进度",
            r"任务.*进度",
            r"check.*status",
        ],
        "required_params": [],
        "optional_params": ["task_id"],
    },
}

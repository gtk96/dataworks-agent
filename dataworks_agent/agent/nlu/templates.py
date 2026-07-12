"""意图模板定义。"""

from __future__ import annotations

from typing import Any

BUSINESS_QUERY_PATTERNS = (
    r"(\u81ea\u4e3b\u95ee\u6570|\u95ee\u6570|\u67e5\u6570|\u67e5\u8be2\u6570\u636e|\u770b\u6570\u636e|\u591a\u5c11\u6761|\u524d\u51e0\u6761)",
    r"(\u67e5\u4e00\u4e0b|\u67e5\u8be2|\u770b\u770b|\u7edf\u8ba1).*?(\u6709\u6548\u8ba2\u5355(?:\u6570|\u91cf)?|\u8ba2\u5355(?:\u6570|\u91cf)|\u9500\u552e\u989d|gmv|\u8f6c\u5316\u7387|\u4eba\u6570|\u6570\u91cf)",
    r"(\u6709\u591a\u5c11|\u591a\u5c11(?:\u6761|\u7b14|\u4e2a)?).*?(\u6709\u6548\u8ba2\u5355(?:\u6570|\u91cf)?|\u8ba2\u5355(?:\u6570|\u91cf)|\u9500\u552e\u989d|gmv|\u8f6c\u5316\u7387|\u4eba\u6570|\u6570\u91cf)",
    r"(\u6709\u6548\u8ba2\u5355(?:\u6570|\u91cf)?|[\u4e00-\u9fff]{0,8}\u8ba2\u5355(?:\u6570|\u91cf)?|\u9500\u552e\u989d|gmv|\u8f6c\u5316\u7387|\u4eba\u6570|\u6570\u91cf).*?(\u662f\u591a\u5c11|\u6709\u591a\u5c11|\u591a\u5c11(?:\u6761|\u7b14|\u4e2a)?|\u60c5\u51b5\u5982\u4f55|\u600e\u4e48\u6837)",
    r"```sql[\s\S]*?select",
)

INTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "cookie_manage": {
        "patterns": [
            r"(cookie|\u767b\u5f55\u6001|9222).*?(\u68c0\u67e5|\u63d0\u53d6|\u5237\u65b0|\u540c\u6b65|\u66f4\u65b0|\u7ba1\u7406)?",
            r"(\u68c0\u67e5|\u63d0\u53d6|\u5237\u65b0|\u540c\u6b65|\u66f4\u65b0|\u7ba1\u7406).*?(cookie|\u767b\u5f55\u6001|9222)",
        ],
        "required_params": [],
        "optional_params": ["goal"],
    },
    "ask_data": {
        "patterns": list(BUSINESS_QUERY_PATTERNS),
        "required_params": [],
        "optional_params": ["goal", "table_name", "source_table"],
    },
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
            r"(\u68c0\u67e5|\u8bca\u65ad|\u6392\u67e5).*?(\u6267\u884c\u5e95\u5ea7|\u8fd0\u884c\u5e95\u5ea7|\u5e95\u5ea7\u5065\u5eb7)",
            r"(\u6267\u884c\u5e95\u5ea7|\u8fd0\u884c\u5e95\u5ea7).*?(\u68c0\u67e5|\u8bca\u65ad|\u5065\u5eb7)",
            r"(self[-_ ]?heal|diagnose|troubleshoot)",
        ],
        "required_params": [],
        "optional_params": ["goal", "task_id", "table_name"],
    },
    "reverse_modeling": {
        "patterns": [
            r"(\u9006\u5411).*?(\u5206\u6790|\u89e3\u6790|\u5efa\u6a21|\u8868\u7ed3\u6784|\u8840\u7f18|\u8bed\u4e49)",
            r"(\u5b58\u91cf).*?(\u5efa\u6a21|\u8868\u7ed3\u6784|\u8840\u7f18|\u8bed\u4e49)",
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
            r"ods.*?(dwd|dim).*?dws",
            r"\u5168\u94fe\u8def.*?(ods|dwd|dim|dws|\u5efa\u8868|\u521d\u59cb\u5316)",
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
    "agent_workflow": {
        "patterns": [
            r"agent.*(处理|完成|规划|执行|自动)",
            r"(端到端|全流程|自动).*?(建模|数仓|dataworks|调度|节点)",
            r"帮我.*?(处理|搞定|完成).*?(dataworks|数仓|建模|节点|调度)",
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

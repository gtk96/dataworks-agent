"""意图模板定义"""

from typing import Any

INTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "create_table": {
        "patterns": [
            r"创建.*表",
            r"新建.*表",
            r"建.*表",
            r"create.*table",
        ],
        "required_params": ["table_name"],
        "optional_params": ["layer", "description"],
    },
    "query_lineage": {
        "patterns": [
            r"查询.*血缘",
            r"查看.*依赖",
            r"query.*lineage",
        ],
        "required_params": ["table_name"],
        "optional_params": ["depth"],
    },
    "check_status": {
        "patterns": [
            r"检查.*状态",
            r"查看.*进度",
            r"check.*status",
        ],
        "required_params": [],
        "optional_params": ["task_id"],
    },
}

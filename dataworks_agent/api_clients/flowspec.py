"""FlowSpec 构建器（Task 8b）— 把建模层的节点配置翻译成 DataWorks OpenAPI
2024-05-18 的节点 Spec（FlowSpec JSON），供 `create_node(spec=)` / `update_node(spec=)`。

结构以真机 `get_node().Node.Spec` 核实（见 CLAUDE.md §7）：
  version=1.1.0, kind=CycleWorkflow, spec.nodes[0]{script,trigger,outputs,...}, spec.flow[]

替代 BFF 的 path/language + updateVertex(cron/trigger) + addNodeDependencies 三步，
统一收敛为单个 FlowSpec。纯函数，无副作用、无网络调用。
"""

from __future__ import annotations

import json
from typing import Any

# 语言 → runtime command / commandTypeId / datasource type / spec 内 script.language 值
# 注：DI 节点真机 spec 为 language="json"、runtime.command="DI"(commandTypeId=23)、datasource=null、
# content=DataX filespec JSON（见 CLAUDE.md §7.7）。
_LANGUAGE_RUNTIME = {
    "odps-sql": {
        "command": "ODPS_SQL",
        "command_type_id": 10,
        "ds_type": "odps",
        "spec_language": "odps-sql",
    },
    "holo": {
        "command": "HOLOGRES_SQL",
        "command_type_id": 1093,
        "ds_type": "holo",
        "spec_language": "holo",
    },
    "di": {"command": "DI", "command_type_id": 23, "ds_type": None, "spec_language": "json"},
}

_DEFAULT_START = "1970-01-01 00:00:00"
_DEFAULT_END = "9999-01-01 00:00:00"


def _map_parameters(parameters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """把 DAILY/HOURLY_SQL_PARAMETERS 形态映射为 FlowSpec 的 Variable 参数。"""
    result: list[dict[str, Any]] = []
    for p in parameters or []:
        result.append(
            {
                "artifactType": "Variable",
                "name": p["name"],
                "scope": p.get("scope", "NodeParameter"),
                "type": p.get("type", "System"),
                "value": p["value"],
            }
        )
    return result


def build_node_flowspec(
    *,
    name: str,
    script_content: str,
    script_path: str,
    output_ref: str,
    language: str = "odps-sql",
    datasource_name: str = "dataworks",
    cron: str,
    cycle_type: str = "NotDaily",
    parameters: list[dict[str, Any]] | None = None,
    cu: str = "0.25",
    timezone: str = "Asia/Shanghai",
    instance_mode: str = "Immediately",
    rerun_mode: str = "Allowed",
    rerun_times: int = 3,
    rerun_interval: int = 180000,
    self_dependency: bool = True,
    auto_parse: bool = True,
    upstream_refs: list[str] | None = None,
    node_id: str | None = None,
) -> str:
    """构建节点 FlowSpec JSON 字符串。

    Args:
        name: 节点名（≈产出表名）。
        script_content: SQL 正文。
        script_path: DataWorks 目录路径（如 业务流程/.../02_DWD/<name>）。
        output_ref: 产出物引用，建议 `<project>.<table>`，用于 outputs 与自依赖。
        language: odps-sql | holo。
        cron / cycle_type / parameters: 调度触发与运行参数。
        self_dependency: 是否加 CrossCycleDependsOnSelf（小时级 ETL 常用）。
        auto_parse: 是否让 DataWorks 从 SQL 自动解析上游依赖。
        upstream_refs: 显式上游产出物引用列表（如 ["dataworks.ods_xxx"]），
            会写入 inputs.nodeOutputs 与 flow.depends（type=Normal），保证上下游硬连接。
        node_id: 更新已有节点时传入其 id；新建留空。

    Returns:
        FlowSpec JSON 字符串。

    Raises:
        ValueError: language 不受支持。
    """
    runtime_map = _LANGUAGE_RUNTIME.get(language)
    if runtime_map is None:
        raise ValueError(f"不支持的 language: {language!r}（支持 {list(_LANGUAGE_RUNTIME)}）")

    runtime: dict[str, Any] = {"command": runtime_map["command"], "cu": cu}
    if runtime_map["command_type_id"] is not None:
        runtime["commandTypeId"] = runtime_map["command_type_id"]

    node: dict[str, Any] = {
        "name": name,
        "recurrence": "Normal",
        "timeout": 0,
        "timeoutUnit": "HOURS",
        "instanceMode": instance_mode,
        "rerunMode": rerun_mode,
        "rerunTimes": rerun_times,
        "rerunInterval": rerun_interval,
        "autoParse": auto_parse,
        # DI 无顶层 datasource（reader/writer 各自在 content 里带）；SQL 类才设
        "datasource": (
            {"name": datasource_name, "type": runtime_map["ds_type"]}
            if runtime_map["ds_type"]
            else None
        ),
        "script": {
            "path": script_path,
            "language": runtime_map["spec_language"],
            "runtime": runtime,
            "content": script_content,
            "parameters": _map_parameters(parameters),
        },
        "trigger": {
            "type": "Scheduler",
            "cron": cron,
            "cycleType": cycle_type,
            "startTime": _DEFAULT_START,
            "endTime": _DEFAULT_END,
            "timezone": timezone,
            "delaySeconds": 0,
        },
        "outputs": {
            "nodeOutputs": [
                {
                    "artifactType": "NodeOutput",
                    "sourceType": "System",
                    "data": output_ref,
                    "refTableName": output_ref,
                    "isDefault": True,
                }
            ]
        },
    }
    if node_id:
        node["id"] = node_id

    if upstream_refs:
        node["inputs"] = {
            "nodeOutputs": [
                {
                    "artifactType": "NodeOutput",
                    "sourceType": "Manual",
                    "data": ref,
                    "refTableName": ref,
                    "isDefault": True,
                }
                for ref in upstream_refs
            ]
        }

    spec: dict[str, Any] = {
        "version": "1.1.0",
        "kind": "CycleWorkflow",
        "spec": {"nodes": [node]},
    }

    depends: list[dict[str, Any]] = []
    if self_dependency:
        depends.append(
            {
                "type": "CrossCycleDependsOnSelf",
                "output": output_ref,
                "refTableName": output_ref,
            }
        )
    for ref in upstream_refs or []:
        depends.append(
            {"type": "Normal", "sourceType": "Manual", "output": ref, "refTableName": ref}
        )

    if depends:
        spec["spec"]["flow"] = [{"nodeId": node_id or name, "depends": depends}]

    return json.dumps(spec, ensure_ascii=False)

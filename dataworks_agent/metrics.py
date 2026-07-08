"""Prometheus 指标 — 任务状态、耗时、通道健康等可观测性数据。"""

from prometheus_client import Counter, Gauge, Histogram, generate_latest

task_total = Counter(
    "dw_modeling_tasks_total",
    "建模任务总数",
    ["status"],
)

task_duration = Histogram(
    "dw_modeling_task_duration_seconds",
    "任务耗时",
    ["layer"],
    buckets=[30, 60, 120, 300, 600, 900],
)

bff_api_duration = Histogram(
    "dw_bff_api_duration_seconds",
    "BFF API 耗时",
    ["endpoint"],
    buckets=[0.5, 1, 2, 5, 10, 15, 30],
)

cdp_errors = Counter(
    "dw_cdp_errors_total",
    "CDP 操作错误数",
    ["operation"],
)

mcp_connections = Gauge(
    "dw_mcp_connections",
    "当前 MCP 连接数",
)

cookie_valid = Gauge(
    "dw_cookie_valid",
    "Cookie 是否有效",
    ["username"],
)


def get_metrics() -> bytes:
    return generate_latest()

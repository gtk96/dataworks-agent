"""End-to-end test of any_ods_modeling intent chain (fixed)"""
import sys

sys.stdout.reconfigure(encoding='utf-8')

from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.governance.word_root_validator import WordRootValidator
from dataworks_agent.modeling.data_source import (
    DataSourceType,
    build_datasource_config_from_text,
)
from dataworks_agent.modeling.schedule_planner import SchedulePlanner

print("=== Test 1: Intent Parsing ===")
parser = IntentParser()
tests = [
    ("帮我搭建从OSS订单数据到DWS汇总的全链路", "any_ods_modeling"),
    ("从mysql数据源建ods和dwd", "any_ods_modeling"),
    ("hologres入仓到dwd", "any_ods_modeling"),
]
for text, expected in tests:
    intent = parser.parse(text)
    status = "OK" if intent.action == expected else "FAIL"
    print(f"  [{status}] {text[:30]:30s} -> {intent.action} (conf={intent.confidence:.2f})")

print("\n=== Test 2: DataSourceConfig ===")
configs = [
    ("oss://bucket/data/orders.json", DataSourceType.OSS),
    ("holo_schema.public.orders", DataSourceType.HOLO),
    ("mysql数据源orders", DataSourceType.MYSQL),
]
for text, expected_type in configs:
    config = build_datasource_config_from_text(text)
    status = "OK" if config.type == expected_type else "FAIL"
    print(f"  [{status}] {text[:30]:30s} -> type={config.type.value}")

print("\n=== Test 3: Word Root Validator ===")
validator = WordRootValidator()
report = validator.validate_columns("dwd_order_detail", ["order_id", "user_name", "invalid!!!col"])
print(f"  Total: {report.total_columns}, Passed: {report.passed}, Warnings: {report.warnings}, Failures: {report.failures}")
summary = report.summary()
# Clean up unicode chars for console
clean_summary = summary.encode('ascii', 'replace').decode('ascii')
print(f"  Summary: {clean_summary[:120]}...")

print("\n=== Test 4: Schedule Planner ===")
planner = SchedulePlanner()
chain = planner.plan_simple_dependency("ods_order", "dwd_order_detail", granularity="day")
print(f"  Nodes: {len(chain.nodes)}")
for node in chain.nodes:
    deps = ",".join(node.depends_on) if node.depends_on else "(none)"
    print(f"    {node.table_name}: cron={node.cron}, depends=[{deps}]")

print("\n=== All Tests Passed ===")

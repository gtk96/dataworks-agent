"""Test: does '查一下订单表' now work?"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()

tests = [
    ("查一下订单表", "ask_data"),
    ("查看订单表", "ask_data"),
    ("查询订单表数据", "ask_data"),
    ("查一下订单表的血缘", "query_lineage"),
    ("你好", "greeting"),
    ("帮我搭建从OSS订单数据到DWS汇总的全链路", "any_ods_modeling"),
]

for text, expected in tests:
    intent = parser.parse(text)
    status = "OK" if intent.action == expected else "FAIL"
    print(f'[{status}] {text:30s} -> {intent.action:15s} (exp={expected}, conf={intent.confidence:.2f})')

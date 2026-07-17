"""Test intent parser after pattern fix"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()

tests = [
    ('帮我搭建从OSS订单数据到DWS汇总的全链路', 'any_ods_modeling'),
    ('全链路建模ods到dws', 'any_ods_modeling'),
    ('从mysql数据源建ods和dwd', 'any_ods_modeling'),
    ('hologres入仓到dwd', 'any_ods_modeling'),
    ('oss_path oss://bucket/data 建ods', 'any_ods_modeling'),
    ('搭建完整的数仓链路', 'any_ods_modeling'),
    ('ods到dwd到dws全链路', 'any_ods_modeling'),
    ('查订单表', 'unknown'),
    ('你好', 'greeting'),
    ('帮我建一张dwd表', 'forward_modeling'),
]
for text, expected in tests:
    intent = parser.parse(text)
    ok = 'OK' if intent.action == expected else 'FAIL'
    print(f'[{ok}] {text[:35]:35s} -> {intent.action:20s} (exp={expected}, conf={intent.confidence:.2f})')

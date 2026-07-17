"""Test intent parser"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()

tests = [
    '帮我搭建从OSS订单数据到DWS汇总的全链路',
    '全链路建模ods到dws',
    '从mysql数据源建ods和dwd',
    'hologres入仓到dwd',
    'oss_path oss://bucket/data 建ods',
    '查订单表',
    '你好',
]
for t in tests:
    intent = parser.parse(t)
    print(f'{t[:40]:40s} -> {intent.action} (conf={intent.confidence:.2f})')

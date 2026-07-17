"""Debug: check if greeting is recognized"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()

tests = [
    "你好",
    "你好！",
    "查一下订单表",
    "帮我搭建从OSS订单数据到DWS汇总的全链路",
]

for text in tests:
    intent = parser.parse(text)
    print(f'{text:30s} -> {intent.action:20s} (conf={intent.confidence:.2f})')

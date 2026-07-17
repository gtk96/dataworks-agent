"""Debug: check if greeting patterns work with actual unicode"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()

# Test with actual unicode characters
tests = [
    "\u4f60\u597d",  # 你好
    "\u67e5\u4e00\u4e0b\u8ba2\u5355\u8868",  # 查一下订单表
    "\u5e2e\u6211\u642d\u5efa\u4eceOSS\u8ba2\u5355\u6570\u636e\u5230DWS\u6c47\u603b\u7684\u5168\u94fe\u8def",  # 帮我搭建从OSS订单数据到DWS汇总的全链路
]

for text in tests:
    intent = parser.parse(text)
    print(f'{repr(text):50s} -> {intent.action:20s} (conf={intent.confidence:.2f})')

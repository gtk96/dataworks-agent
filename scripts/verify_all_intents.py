"""Verify all intents work after fix"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

print(f'Templates: {len(INTENT_TEMPLATES)} keys')
print(f'Keys: {list(INTENT_TEMPLATES.keys())}')
print()

parser = IntentParser()

tests = [
    ("\u4f60\u597d", "greeting"),
    ("\u67e5\u4e00\u4e0b\u8ba2\u5355\u8868", "unknown"),
    ("\u5e2e\u6211\u642d\u5efa\u4eceOSS\u8ba2\u5355\u6570\u636e\u5230DWS\u6c47\u603b\u7684\u5168\u94fe\u8def", "any_ods_modeling"),
    ("\u4ecemysql\u6570\u636e\u6e90\u5efaods\u548cdwd", "any_ods_modeling"),
    ("hologres\u5165\u4ed3\u5230dwd", "any_ods_modeling"),
    ("\u521b\u5efaods_user\u8868", "create_table"),
]

all_pass = True
for text, expected in tests:
    intent = parser.parse(text)
    status = "PASS" if intent.action == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f'[{status}] {text[:30]!r:35s} -> {intent.action:20s} (exp={expected})')

print(f'\nAll passed: {all_pass}')

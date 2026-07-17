"""Debug: check pattern matching"""
import re

from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()

print(f"Testing: {text}")
print(f"Lower: {text_lower}")
print()

# Check any_ods_modeling patterns
for i, pattern in enumerate(INTENT_TEMPLATES["any_ods_modeling"]["patterns"]):
    match = re.search(pattern, text_lower)
    print(f"Pattern {i}: {pattern[:60]}... -> {'MATCH' if match else 'NO MATCH'}")

print()
print("---")
print()

# Check agent_workflow patterns
for i, pattern in enumerate(INTENT_TEMPLATES["agent_workflow"]["patterns"]):
    match = re.search(pattern, text_lower)
    print(f"Pattern {i}: {pattern[:60]}... -> {'MATCH' if match else 'NO MATCH'}")

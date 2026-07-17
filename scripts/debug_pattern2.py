"""Debug: check pattern bytes"""
import re
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()

# Check any_ods_modeling pattern 4 specifically (full-chain)
pattern = INTENT_TEMPLATES["any_ods_modeling"]["patterns"][4]
print(f"Pattern bytes: {pattern.encode('unicode_escape')}")
print(f"Pattern repr: {repr(pattern)}")

# Check if '全链路' is in the text
print(f"text_lower contains '全链路': {'全链路' in text_lower}")
print(f"text_lower contains '全': {'全' in text_lower}")

# Try matching
match = re.search(pattern, text_lower)
print(f"Match result: {match}")

# Try a simpler pattern
simple = r"全链路.*?建模"
match2 = re.search(simple, text_lower)
print(f"Simple pattern match: {match2}")

# Check what the actual text looks like
print(f"text_lower hex: {text_lower.encode('utf-8').hex()}")
print(f"'全链路' hex: {'全链路'.encode('utf-8').hex()}")

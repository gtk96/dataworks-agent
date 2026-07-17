"""Debug: check lowercase matching"""
import re

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()
print(f"text_lower: {repr(text_lower)}")

# The pattern
pattern = r"(\u5168\u94fe\u8def).*?(ods|dwd|dim|dws)"
print(f"pattern: {repr(pattern)}")

# Check if dws is in text_lower
print(f"'dws' in text_lower: {'dws' in text_lower}")
print(f"'全链路' in text_lower: {'全链路' in text_lower}")

# Try simpler pattern
simple = r"全链路.*dws"
print(f"Simple pattern match: {re.search(simple, text_lower)}")

# The issue: the pattern has \u5168 which is '全' but maybe there's a unicode normalization issue
# Let's check byte-by-byte
pat_bytes = pattern.encode('utf-8')
text_bytes = text_lower.encode('utf-8')
print(f"Pattern bytes: {pat_bytes}")
print(f"Text bytes: {text_bytes}")

# Try matching with explicit chars
explicit = r"全链路.*?dws"
print(f"Explicit match: {re.search(explicit, text_lower)}")

# Try with re.IGNORECASE
print(f"Ignore case: {re.search(r'全链路.*?DWS', text_lower, re.IGNORECASE)}")

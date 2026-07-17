"""Debug: hex comparison"""
import re

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()

# The pattern uses \u5168\u94fe\u8def
pattern = r"(\u5168\u94fe\u8def).*?(ods|dwd|dim|dws)"
print(f"Pattern: {pattern!r}")
print(f"Pattern decoded: {pattern}")

# Does the text contain 全链路?
print(f"text_lower: {text_lower!r}")
print(f"'全链路' in text_lower: {'全链路' in text_lower}")

# Try direct match
match = re.search(pattern, text_lower)
print(f"Direct match: {match}")

# Try character by character
idx = text_lower.find('全')
if idx >= 0:
    print(f"Found '全' at index {idx}")
    print(f"Context: {text_lower[idx:idx+10]!r}")
else:
    print("'全' not found in text")

# Check if the pattern unicode escapes are actually the same chars
pat_str = pattern.encode('utf-8').decode('unicode_escape')
print(f"Pattern after decode: {pat_str!r}")
print(f"Does pat_str contain '全链路': {'全链路' in pat_str}")

# Try compiling and matching
compiled = re.compile(pattern)
print(f"Compiled pattern: {compiled.pattern}")
print(f"Match: {compiled.search(text_lower)}")

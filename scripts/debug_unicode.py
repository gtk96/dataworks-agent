"""Deep debug: unicode normalization"""
import re
import unicodedata

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()

# Check if text has any weird unicode
for i, c in enumerate(text_lower):
    if ord(c) > 127:
        print(f"Char {i}: '{c}' U+{ord(c):04X} {unicodedata.name(c, '?')}")

print()
print(f"Full text_lower: {repr(text_lower)}")
print(f"Full text_lower hex: {text_lower.encode('utf-8').hex()}")

# Check the pattern
pattern = r"全链路.*?dws"
print(f"\nPattern: {repr(pattern)}")
print(f"Pattern hex: {pattern.encode('utf-8').hex()}")

# NFKC normalize both
norm_text = unicodedata.normalize('NFKC', text_lower)
norm_pat = unicodedata.normalize('NFKC', pattern)
print(f"\nNorm text: {repr(norm_text)}")
print(f"Norm pat: {repr(norm_pat)}")

match = re.search(norm_pat, norm_text)
print(f"NFKC match: {match}")

# Try matching individual chars
print(f"\n'text_lower[19:22] = {repr(text_lower[19:22])}')
print(f"'pattern[1:4] = {repr(pattern[1:4])}')
print(f"Equal: {text_lower[19:22] == pattern[1:4]}")

# Try with raw bytes
print(f"\ntext_lower[19:22].encode('utf-8'): {text_lower[19:22].encode('utf-8')}")
print(f"pattern[1:4].encode('utf-8'): {pattern[1:4].encode('utf-8')}")

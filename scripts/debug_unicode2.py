"""Deep debug: unicode normalization"""
import re
import unicodedata

text = "帮我搭建从OSS订单数据到DWS汇总的全链路"
text_lower = text.lower().strip()

# Check if text has any weird unicode
for i, c in enumerate(text_lower):
    if ord(c) > 127:
        print(f"Char {i}: '{c}' U+{ord(c):04X}")

print()
print("Full text_lower:", repr(text_lower))
print("Full text_lower hex:", text_lower.encode('utf-8').hex())

# Check the pattern
pattern = r"全链路.*?dws"
print()
print("Pattern:", repr(pattern))
print("Pattern hex:", pattern.encode('utf-8').hex())

# NFKC normalize both
norm_text = unicodedata.normalize('NFKC', text_lower)
norm_pat = unicodedata.normalize('NFKC', pattern)
print()
print("Norm text:", repr(norm_text))
print("Norm pat:", repr(norm_pat))

match = re.search(norm_pat, norm_text)
print("NFKC match:", match)

# Try matching individual chars
t_slice = text_lower[19:22]
p_slice = pattern[1:4]
print()
print("text_lower[19:22] =", repr(t_slice))
print("pattern[1:4] =", repr(p_slice))
print("Equal:", t_slice == p_slice)

# Try with raw bytes
print()
print("text slice encode:", t_slice.encode('utf-8'))
print("pat slice encode:", p_slice.encode('utf-8'))

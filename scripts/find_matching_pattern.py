"""Find which pattern matches '创建ods_user表'"""
import re

from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

text = "\u521b\u5efaods_user\u8868"
text_lower = text.lower()

print(f'Text: {text}')
print(f'Lower: {text_lower}')
print()

# Check any_ods_modeling patterns
for i, pattern in enumerate(INTENT_TEMPLATES["any_ods_modeling"]["patterns"]):
    match = re.search(pattern, text_lower)
    if match:
        print(f'Pattern {i} MATCHED: {pattern[:60]}... -> {match.group()}')

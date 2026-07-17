"""Check greeting pattern in templates"""
import re

from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

greeting_patterns = INTENT_TEMPLATES["greeting"]["patterns"]
print(f"Greeting patterns: {len(greeting_patterns)}")
for i, p in enumerate(greeting_patterns):
    print(f'  {i}: {repr(p)[:80]}')

# Test with actual unicode
text = "\u4f60\u597d"
print(f'\nTest text: {text!r}')
print(f'Test text decoded: {text}')

for i, pattern in enumerate(greeting_patterns):
    match = re.search(pattern, text)
    print(f'Pattern {i}: match={bool(match)}')

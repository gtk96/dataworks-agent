"""Check what the test sends"""
with open('tests/unit/test_agent/test_core.py', encoding='utf-8') as f:
    content = f.read()

import re

# Find the test function
match = re.search(r'async def test_agent_chat_create_table.*?(?=async def |\Z)', content, re.DOTALL)
if match:
    print(match.group(0)[:500])

"""Show the actual test input messages"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re

# Find test_parser_recognizes_mysql_ods_dwd_entities
match = re.search(r'def test_parser_recognizes_mysql.*?(?=def |\Z)', content, re.DOTALL)
if match:
    block = match.group(0)
    # Find the message/text being parsed
    msgs = re.findall(r'(?:parse|IntentParser|parser\.parse)\s*\(\s*["\']([^"\']+)["\']', block)
    for m in msgs:
        print(f'Message: {m}')

# Find test_planner_adds_ods_dwd_steps
match = re.search(r'def test_planner_adds_ods_dwd_steps.*?(?=async def |\Z)', content, re.DOTALL)
if match:
    block = match.group(0)
    msgs = re.findall(r'(?:message|text|prompt)\s*=\s*["\']([^"\']+)["\']', block)
    for m in msgs:
        print(f'Message: {m}')

# Find test_chat_agent_full_ods_dwd_flow_collects_artifacts
match = re.search(r'async def test_chat_agent_full_ods_dwd_flow.*?(?=def |\Z)', content, re.DOTALL)
if match:
    block = match.group(0)
    msgs = re.findall(r'(?:message|text|prompt)\s*=\s*["\']([^"\']+)["\']', block)
    for m in msgs:
        print(f'Message: {m}')

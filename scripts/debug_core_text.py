"""Debug: find the exact text"""
with open('dataworks_agent/agent/core.py', 'r', encoding='utf-8') as f:
    content = f.read()

idx = content.find('workflow_actions = {')
if idx >= 0:
    print(repr(content[idx:idx+500]))
else:
    print('Not found')

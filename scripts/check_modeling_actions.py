"""Check if create_table is in workflow_actions"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines[:60]):
    print(f'{i+1}: {line.rstrip()}')

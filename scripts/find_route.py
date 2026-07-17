"""Find _route_action method"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '_route_action' in line:
        print(f'{i+1}: {line.rstrip()}')

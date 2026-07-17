"""Show _route_action method"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(618, 680):
    print(f'{i+1}: {lines[i].rstrip()}')

"""Show _execute_once method"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(214, 350):
    print(f'{i+1}: {lines[i].rstrip()}')

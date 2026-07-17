"""Find _forward_model method"""
with open('dataworks_agent/agent/workflow_service.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'def _forward_model' in line:
        print(f'{i+1}: {line.rstrip()}')

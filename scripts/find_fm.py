"""Find forward_modeling handling in workflow_service.py"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'forward_modeling' in line.lower() or 'any_ods' in line.lower():
        print(f'{i+1}: {line.rstrip()}')

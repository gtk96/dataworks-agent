"""Check workflow_service.py structure"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
print(f'Total lines: {len(lines)}')
for i, line in enumerate(lines):
    if 'def execute' in line or 'def _execute' in line or 'def _attach' in line:
        print(f'{i+1}: {line.rstrip()}')

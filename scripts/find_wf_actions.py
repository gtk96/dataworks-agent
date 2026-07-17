"""Find workflow_actions in workflow_service.py"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'workflow_actions' in line or 'forward_modeling' in line:
        if i < 250:  # Only in the execute method area
            print(f'{i+1}: {line.rstrip()}')

"""Show full plan method"""
with open('dataworks_agent/agent/planner/task_planner.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'def plan' in line or 'forward_modeling' in line or 'ods_dwd' in line or 'any_ods' in line:
        print(f'{i+1}: {line.rstrip()}')

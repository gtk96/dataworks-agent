"""Find TASK_TEMPLATES"""
with open('dataworks_agent/agent/planner/task_planner.py', 'r', encoding='utf-8') as f:
    content = f.read()

for kw in ['TASK_TEMPLATES', 'TEMPLATES', 'templates', 'PLAN_TEMPLATES']:
    idx = content.find(kw)
    if idx >= 0:
        print(f'{kw} found at {idx}: {repr(content[idx:idx+50])}')

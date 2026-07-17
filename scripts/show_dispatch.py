"""Show execute method dispatch logic"""
with open('dataworks_agent/agent/workflow_service.py', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(130, 175):
    print(f'{i+1}: {lines[i].rstrip()}')

"""Show the execute method structure"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show lines 240-280
for i in range(240, min(280, len(lines))):
    print(f'{i+1}: {lines[i].rstrip()}')

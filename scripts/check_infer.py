"""Check infer_mode"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'def infer_mode' in line:
        for j in range(i, min(i+15, len(lines))):
            print(f'{j+1}: {lines[j].rstrip()}')
        break

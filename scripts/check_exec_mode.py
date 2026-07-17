"""Check what happens with execution_mode=None"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show the execute method
for i in range(132, 165):
    print(f'{i+1}: {lines[i].rstrip()}')

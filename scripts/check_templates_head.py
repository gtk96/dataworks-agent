"""Check templates.py structure"""
with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show first 30 lines
for i in range(min(30, len(lines))):
    print(f'{i+1}: {repr(lines[i])}')

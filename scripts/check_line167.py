"""Check line 167 of templates.py"""
with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(max(0, 162), min(len(lines), 175)):
    print(f'{i+1}: {repr(lines[i])}')

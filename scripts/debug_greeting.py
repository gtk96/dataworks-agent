"""Fix greeting and other simple intents bypassing workflow"""
with open('dataworks_agent/agent/core.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the greeting handling section and fix it
for i, line in enumerate(lines):
    if 'intent.action == "greeting"' in line:
        print(f'Found greeting at line {i+1}: {line.rstrip()}')
        # Check what happens after
        for j in range(i, min(i+10, len(lines))):
            print(f'{j+1}: {lines[j].rstrip()}')
        break

"""Debug: trace the greeting flow"""
with open('dataworks_agent/agent/core.py', encoding='utf-8') as f:
    lines = f.readlines()

# Show lines 130-175 to see the full flow
for i in range(128, 175):
    print(f'{i+1}: {lines[i].rstrip()}')

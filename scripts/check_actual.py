"""Check actual test content"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show lines around 68-72
for i in range(66, 75):
    print(f'{i+1}: {lines[i].rstrip()}')

print('---')

# Show lines around 83-86
for i in range(81, 90):
    print(f'{i+1}: {lines[i].rstrip()}')

print('---')

# Show lines around 150-155
for i in range(148, 158):
    print(f'{i+1}: {lines[i].rstrip()}')

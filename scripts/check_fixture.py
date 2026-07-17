"""Check test_core.py fixture"""
with open('tests/unit/test_agent/test_core.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show the fixture definition
for i, line in enumerate(lines):
    if '@pytest.fixture' in line or 'def agent' in line:
        for j in range(i, min(i+10, len(lines))):
            print(f'{j+1}: {lines[j].rstrip()}')
        print('---')

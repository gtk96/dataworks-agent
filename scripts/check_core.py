"""Check test_core.py failure"""
with open('tests/unit/test_agent/test_core.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'test_agent_chat_create_table' in line or 'create_table' in line.lower():
        print(f'{i+1}: {line.rstrip()}')
        for j in range(i+1, min(i+15, len(lines))):
            if lines[j].strip().startswith('def ') and j > i+1:
                break
            print(f'  {j+1}: {lines[j].rstrip()}')

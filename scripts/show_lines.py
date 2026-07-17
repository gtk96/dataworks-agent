with open('tests/unit/test_agent_ods_dwd.py', encoding='utf-8') as f:
    lines = f.readlines()
for i in [69, 84, 151]:
    print(f'{i+1}: {lines[i]!r}')

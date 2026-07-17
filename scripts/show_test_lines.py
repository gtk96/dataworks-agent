"""Show test messages directly"""
with open('tests/unit/test_agent_ods_dwd.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'test_parser_recognizes_mysql' in line:
        for j in range(i, min(i+20, len(lines))):
            if 'parse(' in lines[j] or 'message=' in lines[j] or 'text=' in lines[j]:
                print(f'{j+1}: {lines[j].rstrip()}')
    if 'test_planner_adds_ods_dwd' in line:
        for j in range(i, min(i+30, len(lines))):
            if 'message=' in lines[j] or 'text=' in lines[j] or 'parse(' in lines[j]:
                print(f'{j+1}: {lines[j].rstrip()}')
    if 'test_chat_agent_full_ods_dwd' in line:
        for j in range(i, min(i+40, len(lines))):
            if 'message=' in lines[j] or 'text=' in lines[j] or 'parse(' in lines[j] or 'action=' in lines[j]:
                print(f'{j+1}: {lines[j].rstrip()}')

"""Check failing test inputs"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show test_parser_recognizes_mysql_ods_dwd_entities
in_test = False
for i, line in enumerate(lines):
    if 'test_parser_recognizes_mysql' in line or 'test_planner_adds' in line or 'test_chat_agent_full' in line:
        in_test = True
        print(f'\n--- {line.rstrip()} ---')
    if in_test:
        if line.strip().startswith('def ') and 'test_' in line and 'mysql' not in line and 'planner' not in line and 'chat_agent_full' not in line:
            in_test = False
        elif 'message' in line.lower() and ('=' in line or ':' in line):
            print(f'  {line.rstrip()}')
        elif in_test and i < 200:
            # Print context around key lines
            if any(kw in line for kw in ['message', 'text', 'prompt', '"ods', '"dwd', '"mysql', 'any_ods']):
                print(f'  {line.rstrip()}')

"""Fix test_parse_query_table_without_lineage_keyword"""
with open('tests/unit/test_agent/test_intent_parser.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'test_parse_query_table_without_lineage_keyword' in line:
        # Show the test
        for j in range(i, min(i+15, len(lines))):
            print(f'{j+1}: {lines[j].rstrip()}')
        break

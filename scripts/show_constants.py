"""Show MYSQL_ODS_DWD constant"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'MYSQL_ODS_DWD' in line and '=' in line and ('"' in line or "'" in line):
        print(f'{i+1}: {line.rstrip()}')
    if 'HOLO_ODS_DWD' in line and '=' in line and ('"' in line or "'" in line):
        print(f'{i+1}: {line.rstrip()}')
    if 'OSS_ODS_DWD' in line and '=' in line and ('"' in line or "'" in line):
        print(f'{i+1}: {line.rstrip()}')

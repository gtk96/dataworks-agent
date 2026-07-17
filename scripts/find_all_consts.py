"""Find all ODS_DWD related constants"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'ODS_DWD' in line and ('=' in line or 'MYSQL' in line or 'HOLO' in line or 'OSS' in line):
        print(f'{i+1}: {line.rstrip()}')
        # Also show next few lines if multiline
        for j in range(i+1, min(i+5, len(lines))):
            if lines[j].strip() and not lines[j].strip().startswith('#'):
                print(f'  {j+1}: {lines[j].rstrip()}')
                if lines[j].strip().endswith("'") or lines[j].strip().endswith('"""'):
                    break

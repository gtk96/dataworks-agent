"""Check the outcome verifier for any_ods_modeling"""
with open('dataworks_agent/agent/outcome_verifier.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'source_type' in line or 'oss_path' in line or 'missing' in line.lower() or 'verify' in line.lower():
        print(f'{i+1}: {line.rstrip()}')

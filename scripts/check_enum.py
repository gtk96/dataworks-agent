"""Check FileFormat enum values"""
with open('dataworks_agent/modeling/data_source.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'class FileFormat' in line or 'JSON' in line or 'CSV' in line or 'PARQUET' in line:
        print(f'{i+1}: {line.rstrip()}')

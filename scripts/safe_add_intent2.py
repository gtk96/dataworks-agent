"""Safely add any_ods_modeling using line-by-line approach"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "check_status":
insert_line = None
for i, line in enumerate(lines):
    if '"check_status":' in line:
        insert_line = i
        break

if insert_line is None:
    print('ERROR: check_status not found')
    exit(1)

print(f'Found check_status at line {insert_line+1}')

# Insert any_ods_modeling before check_status
new_intent_lines = [
    '    "any_ods_modeling": {\n',
    '        "patterns": [\n',
    '            r"(oss|对象存储|\\\\.json|\\\\.csv|\\\\.parquet).*?(ods|入仓|贴源|建模)",\n',
    '            r"oss_path.*?ods",\n',
    '            r"(holo|hologres|实时).*?(ods|入仓|建模)",\n',
    '            r"(mysql|polardb|postgres|关系型).*?(ods|入仓|建模)",\n',
    '            r"(全链路|端到端|完整链路).*?(ods|dwd|dim|dws|建模|数仓)",\n',
    '            r"(ods|dwd|dim|dws).*?(全链路|端到端|完整链路|建模)",\n',
    '            r"(搭建|创建|建).*?(全链路|ods|dwd|dws|数仓|建模)",\n',
    '            r"(全链路|ods|dwd|dws).*?(搭建|创建|建)",\n',
    '            r"(oss|hologres|mysql|polardb|postgres).*?(全链路|端到端|完整链路|入仓)",\n',
    '            r"(全链路|端到端|完整链路).*?(oss|hologres|mysql|polardb|postgres)",\n',
    '        ],\n',
    '        "required_params": [],\n',
    '        "optional_params": [\n',
    '            "goal", "table_name", "source_table", "layer", "domain",\n',
    '            "schedule_cycle", "source_type", "datasource_name", "oss_path",\n',
    '            "file_format", "ods_table", "dwd_table", "dim_table", "dws_table",\n',
    '            "task_id", "dev_schema", "granularity", "schedule_minute",\n',
    '            "holo_schema", "holo_table", "database", "sync_mode",\n',
    '            "incremental_column",\n',
    '        ],\n',
    '    },\n',
]

lines = lines[:insert_line] + new_intent_lines + lines[insert_line:]

with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

# Verify
try:
    with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
        compile(f.read(), 'templates.py', 'exec')
    print('SUCCESS: templates.py compiles correctly')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')

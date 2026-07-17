"""Safely add any_ods_modeling without breaking templates.py"""
import ast

with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Verify greeting exists before modification
try:
    templates = ast.literal_eval(content.split('INTENT_TEMPLATES:')[1].rsplit('\n\n', 1)[0] + '\n}')
    print(f'Before: {len(templates)} keys, greeting present: {"greeting" in templates}')
except:
    print('Could not parse before modification')

# Find the last key in the dict (check_status) and insert before it
check_status_pos = content.find('"check_status":')
if check_status_pos < 0:
    print('ERROR: check_status not found')
    exit(1)

new_intent = '''    "any_ods_modeling": {
        "patterns": [
            r"(oss|对象存储|\\.json|\\.csv|\\.parquet).*?(ods|入仓|贴源|建模)",
            r"oss_path.*?ods",
            r"(holo|hologres|实时).*?(ods|入仓|建模)",
            r"(mysql|polardb|postgres|关系型).*?(ods|入仓|建模)",
            r"(全链路|端到端|完整链路).*?(ods|dwd|dim|dws|建模|数仓)",
            r"(ods|dwd|dim|dws).*?(全链路|端到端|完整链路|建模)",
            r"(搭建|创建|建).*?(全链路|ods|dwd|dws|数仓|建模)",
            r"(全链路|ods|dwd|dws).*?(搭建|创建|建)",
            r"(oss|hologres|mysql|polardb|postgres).*?(全链路|端到端|完整链路|入仓)",
            r"(全链路|端到端|完整链路).*?(oss|hologres|mysql|polardb|postgres)",
        ],
        "required_params": [],
        "optional_params": [
            "goal", "table_name", "source_table", "layer", "domain",
            "schedule_cycle", "source_type", "datasource_name", "oss_path",
            "file_format", "ods_table", "dwd_table", "dim_table", "dws_table",
            "task_id", "dev_schema", "granularity", "schedule_minute",
            "holo_schema", "holo_table", "database", "sync_mode",
            "incremental_column",
        ],
    },
'''

content = content[:check_status_pos] + new_intent + content[check_status_pos:]

with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify after modification
try:
    templates = ast.literal_eval(content.split('INTENT_TEMPLATES:')[1].rsplit('\n\n', 1)[0] + '\n}')
    print(f'After: {len(templates)} keys, greeting present: {"greeting" in templates}, any_ods present: {"any_ods_modeling" in templates}')
except Exception as e:
    print(f'Parse error after: {e}')

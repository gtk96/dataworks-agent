"""Script to add any_ods_modeling intent to templates.py"""
import re

with open("dataworks_agent/agent/nlu/templates.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find forward_modeling section end
idx = content.find('"forward_modeling"')
if idx < 0:
    print("ERROR: forward_modeling not found")
    exit(1)

# Find the closing brace of forward_modeling
brace_count = 0
started = False
end_idx = idx
for i, c in enumerate(content[idx:], idx):
    if c == "{":
        brace_count += 1
        started = True
    elif c == "}":
        brace_count -= 1
        if started and brace_count == 0:
            end_idx = i + 1
            break

print(f"Found forward_modeling at {idx}, ends at {end_idx}")

# Insert new section after forward_modeling
new_section = '''
    "any_ods_modeling": {
        "patterns": [
            r"(oss|对象存储|\\.json|\\.csv|\\.parquet).*?(ods|入仓|贴源)",
            r"oss_path.*?ods",
            r"(holo|hologres|实时).*?(ods|入仓)",
            r"(mysql|polardb|postgres|关系型).*?(ods|入仓)",
            r"(全链路|端到端|完整链路).*?(ods|dwd|dim|dws)",
            r"(建|搭|创建|搭建).*?(ods.*?dwd|ods.*?dws|ods.*?dim)",
            r"全链路.*?建模",
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

content = content[:end_idx] + new_section + content[end_idx:]

with open("dataworks_agent/agent/nlu/templates.py", "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: any_ods_modeling intent added")

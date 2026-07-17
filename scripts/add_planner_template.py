"""Add any_ods_modeling template to TaskPlanner"""
with open('dataworks_agent/agent/planner/task_planner.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the forward_modeling template and add any_ods_modeling before it
# Or find the TASK_TEMPLATES dict and add the new key

# The template structure is like:
# "forward_modeling": {
#     "description": "...",
#     "steps": [...]
# }

# Add any_ods_modeling with the same steps as forward_modeling/ods_dwd_modeling
# Find the closing of the last template before plan method

import re

# Find the TASK_TEMPLATES definition
match = re.search(r'TASK_TEMPLATES\s*=\s*\{', content)
if not match:
    print('TASK_TEMPLATES not found')
    exit(1)

# Find the forward_modeling template
fm_match = re.search(r'"forward_modeling":\s*\{', content)
if not fm_match:
    print('forward_modeling template not found')
    exit(1)

# The any_ods_modeling template should be identical to forward_modeling
# since they both do the same thing (full-chain modeling from any source)
any_ods_template = '''    "any_ods_modeling": {
        "description": "Full-chain data modeling from any source (OSS/Holo/MySQL/PG) to ODS/DWD/DIM/DWS layers with scheduling and dependency configuration.",
        "steps": [
            {
                "tool": "analyze_ods_dwd_requirement",
                "params": {"goal": "{{goal}}", "source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "source_table": "{{source_table}}", "target_table": "{{table_name}}", "domain": "{{domain}}", "entity": "{{entity}}", "layers": "{{layers}}", "schedule_cycle": "{{schedule_cycle}}", "granularity": "{{granularity}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "logical_primary_keys": "{{logical_primary_keys}}", "json_field_mappings": "{{json_field_mappings}}", "oss_path": "{{oss_path}}", "file_format": "{{file_format}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}"},
                "description": "Analyze the ODS→DWD requirement and determine the modeling approach."
            },
            {
                "tool": "classify_ods_source",
                "params": {"source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "source_table": "{{source_table}}", "oss_path": "{{oss_path}}", "file_format": "{{file_format}}", "granularity": "{{granularity}}", "schedule_cycle": "{{schedule_cycle}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}", "table_name": "{{table_name}}", "domain": "{{domain}}", "entity": "{{entity}}", "logical_primary_keys": "{{logical_primary_keys}}", "json_field_mappings": "{{json_field_mappings}}", "data_profile": "{{data_profile}}"},
                "description": "Classify the ODS source type and determine the ingestion strategy."
            },
            {
                "tool": "plan_ods_pipeline",
                "params": {"source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "source_table": "{{source_table}}", "target_table": "{{ods_table}}", "granularity": "{{granularity}}", "schedule_cycle": "{{schedule_cycle}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "partition_keys": "{{partition_keys}}", "schedule_minute": "{{schedule_minute}}", "ods_sql_directory": "{{ods_sql_directory}}"},
                "description": "Plan the ODS pipeline (external table + extract SQL + node + schedule)."
            },
            {
                "tool": "preview_dwd_artifacts",
                "params": {"source_table": "{{source_table}}", "target_table": "{{dwd_table}}", "domain": "{{domain}}", "entity": "{{entity}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "partition_keys": "{{partition_keys}}", "logical_primary_keys": "{{logical_primary_keys}}", "json_field_mappings": "{{json_field_mappings}}", "data_profile": "{{data_profile}}", "source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "granularity": "{{granularity}}", "schedule_cycle": "{{schedule_cycle}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}", "table_name": "{{table_name}}"},
                "description": "Generate DWD DDL/DML preview with field mapping and update mode inference."
            },
            {
                "tool": "plan_ods_dwd_dependencies",
                "params": {"source_table": "{{source_table}}", "target_table": "{{dwd_table}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "schedule_cycle": "{{schedule_cycle}}", "granularity": "{{granularity}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}", "table_name": "{{table_name}}", "domain": "{{domain}}", "entity": "{{entity}}"},
                "description": "Plan ODS→DWD dependency chain with cross-cycle self-dependency and root node wiring."
            },
            {
                "tool": "validate_guardrails",
                "params": {"table_name": "{{table_name}}", "domain": "{{domain}}", "entity": "{{entity}}", "source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "source_table": "{{source_table}}", "target_table": "{{dwd_table}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "schedule_cycle": "{{schedule_cycle}}", "granularity": "{{granularity}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}", "logical_primary_keys": "{{logical_primary_keys}}", "json_field_mappings": "{{json_field_mappings}}", "data_profile": "{{data_profile}}", "oss_path": "{{oss_path}}", "file_format": "{{file_format}}"},
                "description": "Validate guardrails: table naming, publish gate readiness, write safety."
            },
            {
                "tool": "recommend_next_actions",
                "params": {"table_name": "{{table_name}}", "domain": "{{domain}}", "entity": "{{entity}}", "source_type": "{{source_type}}", "datasource_name": "{{datasource_name}}", "source_table": "{{source_table}}", "target_table": "{{dwd_table}}", "dev_schema": "{{dev_schema}}", "prod_schema": "{{prod_schema}}", "schedule_cycle": "{{schedule_cycle}}", "granularity": "{{granularity}}", "ods_table": "{{ods_table}}", "dwd_table": "{{dwd_table}}", "logical_primary_keys": "{{logical_primary_keys}}", "json_field_mappings": "{{json_field_mappings}}", "data_profile": "{{data_profile}}", "oss_path": "{{oss_path}}", "file_format": "{{file_format}}"},
                "description": "Recommend next actions: inspect artifacts, clarify missing context, or proceed to execution."
            },
        ],
    },
'''

# Insert before forward_modeling
content = content[:fm_match.start()] + any_ods_template + content[fm_match.start():]

with open('dataworks_agent/agent/planner/task_planner.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS: added any_ods_modeling template')

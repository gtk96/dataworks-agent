"""Add extraction calls for new any_ods_modeling params"""
with open('dataworks_agent/agent/nlu/entity_extractor.py', encoding='utf-8') as f:
    content = f.read()

# Find the extract_params method and add new extractions
# Add before "if 'goal' in wanted:"
goal_check = "        if \"goal\" in wanted:"
if goal_check in content:
    new_extractions = '''        if "holo_schema" in wanted:
            holo_schema = self.extract_holo_schema(text)
            if holo_schema:
                params["holo_schema"] = holo_schema
        if "database" in wanted:
            database = self.extract_database(text)
            if database:
                params["database"] = database
        if "sync_mode" in wanted:
            sync_mode = self.extract_sync_mode(text)
            if sync_mode:
                params["sync_mode"] = sync_mode
        if "incremental_column" in wanted:
            incremental_column = self.extract_incremental_column(text)
            if incremental_column:
                params["incremental_column"] = incremental_column
'''
    content = content.replace(goal_check, new_extractions + goal_check)
    print('SUCCESS: added new param extractions')
else:
    print('ERROR: goal check not found')

with open('dataworks_agent/agent/nlu/entity_extractor.py', 'w', encoding='utf-8') as f:
    f.write(content)

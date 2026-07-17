"""Add any_ods_modeling to loop policy and routing"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add to loop policy
old_policy = 'if workflow_type == "forward_modeling":'
new_policy = '''if workflow_type in ("forward_modeling", "any_ods_modeling"):'''

if old_policy in content:
    content = content.replace(old_policy, new_policy)
    print('Step 1: Updated loop policy')
else:
    print('Step 1: Pattern not found')

# 2. Add to _infer_workflow_type if it exists
# Find where forward_modeling is used as a default
# Look for patterns like '"forward_modeling"' in the execute method area
# The key is to add 'any_ods_modeling' wherever 'forward_modeling' is checked

# Count occurrences
count = content.count('"forward_modeling"')
print(f'Step 2: Found {count} occurrences of "forward_modeling"')

# For the routing, we need to add any_ods_modeling handling in the execute method
# Find where the workflow dispatch happens
# Look for the section where action is checked

with open('dataworks_agent/agent/workflow_service.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')

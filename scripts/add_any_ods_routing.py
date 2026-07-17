"""Add any_ods_modeling routing to workflow_service.py"""

with open('dataworks_agent/agent/workflow_service.py', encoding='utf-8') as f:
    content = f.read()

# Find the workflow_actions set in execute method
# It should be around line 132-214
actions_idx = content.find('workflow_actions = {')
if actions_idx < 0:
    print('ERROR: workflow_actions not found')
    exit(1)

# Find the closing of workflow_actions
brace_count = 0
started = False
end_idx = actions_idx
for i, c in enumerate(content[actions_idx:], actions_idx):
    if c == '{':
        brace_count += 1
        started = True
    elif c == '}':
        brace_count -= 1
        if started and brace_count == 0:
            end_idx = i + 1
            break

# Add any_ods_modeling to the set
old_block = content[actions_idx:end_idx]
new_block = old_block.replace(
    '"forward_modeling"',
    '"forward_modeling",\n                "any_ods_modeling"'
)

if old_block != new_block:
    content = content[:actions_idx] + new_block + content[end_idx:]
    print('SUCCESS: added any_ods_modeling to workflow_actions')
else:
    print('No change needed or pattern not found')

# Also need to add routing for any_ods_modeling in the execute method
# Find where forward_modeling is handled and add any_ods_modeling alongside it
# Look for the condition that checks intent.action in workflow_actions
# and adds _execute_once calls

with open('dataworks_agent/agent/workflow_service.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
print('Verifying...')
try:
    compile(content, 'workflow_service.py', 'exec')
    print('Syntax OK')
except SyntaxError as e:
    print(f'Syntax error: {e}')

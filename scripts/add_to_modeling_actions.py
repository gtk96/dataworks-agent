"""Add any_ods_modeling to _MODELING_ACTIONS"""
with open('dataworks_agent/agent/workflow_service.py', encoding='utf-8') as f:
    content = f.read()

old = '_MODELING_ACTIONS = {"agent_workflow", "ods_dwd_modeling", "forward_modeling"}'
new = '_MODELING_ACTIONS = {"agent_workflow", "ods_dwd_modeling", "forward_modeling", "any_ods_modeling"}'

if old in content:
    content = content.replace(old, new)
    with open('dataworks_agent/agent/workflow_service.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: added any_ods_modeling to _MODELING_ACTIONS')
else:
    print('Pattern not found, checking...')
    idx = content.find('_MODELING_ACTIONS')
    if idx >= 0:
        print(f'Found at {idx}: {content[idx:idx+100]!r}')
    else:
        print('Not found at all')

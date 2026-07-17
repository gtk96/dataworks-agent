with open('dataworks_agent/agent/core.py', encoding='utf-8') as f:
    content = f.read()
print('any_ods_modeling' in content)
idx = content.find('workflow_actions = {')
if idx >= 0:
    print(content[idx:idx+300])

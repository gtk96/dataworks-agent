"""Check original templates.py"""
import subprocess
result = subprocess.run(['git', 'show', 'HEAD:dataworks_agent/agent/nlu/templates.py'], capture_output=True, text=True, encoding='utf-8')
content = result.stdout
print('greeting' in content)
print('cookie_manage' in content)
idx = content.find('INTENT_TEMPLATES')
if idx >= 0:
    print(content[idx:idx+300])

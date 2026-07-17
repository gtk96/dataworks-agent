"""Find constants"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
# Find constant definitions
for m in re.finditer(r'^([A-Z_]+_ODS_DWD)\s*=\s*r?["\'](.+?)["\']', content, re.MULTILINE | re.DOTALL):
    name = m.group(1)
    val = m.group(2)[:80]
    print(f'{name} = {repr(val)}...')

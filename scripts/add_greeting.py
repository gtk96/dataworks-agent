"""Add greeting intent to templates.py"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the first key in INTENT_TEMPLATES (should be cookie_manage at line 18)
# and insert greeting before it
insert_line = None
for i, line in enumerate(lines):
    if '"cookie_manage":' in line:
        insert_line = i
        break

if insert_line is None:
    print('ERROR: cookie_manage not found')
    exit(1)

greeting_lines = [
    '    "greeting": {\n',
    '        "patterns": [\n',
    '            r"^(\\u4f60\\u597d|hi|hello|hey|\\u55a8|\\u65e9\\u4e0a\\u597d|\\u4e0b\\u5348\\u597d|\\u665a\\u4e0a\\u597d|\\u5728\\u5417|\\u5728\\u4e0d\\u5728)[\\s!\\uff01。\\。.]*$",\n',
    '            r"^(\\u4f60\\u597d|hi|hello|hey|\\u55a8|\\u65e9\\u4e0a\\u597d|\\u4e0b\\u5348\\u597d|\\u665a\\u4e0a\\u597d|\\u5728\\u5417|\\u5728\\u4e0d\\u5728)[\\s!\\uff01。\\。.]*",\n',
    '        ],\n',
    '        "required_params": [],\n',
    '        "optional_params": [],\n',
    '    },\n',
]

lines = lines[:insert_line] + greeting_lines + lines[insert_line:]

with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

# Verify
try:
    with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
        compile(f.read(), 'templates.py', 'exec')
    print('SUCCESS: templates.py compiles correctly with greeting')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')

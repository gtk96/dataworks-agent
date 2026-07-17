"""Remove overly broad pattern that catches create_table"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    content = f.read()

# Remove the two problematic patterns
content = content.replace(
    '            r"(搭建|创建|建).*?(全链路|ods|dwd|dws|数仓|建模)",\n',
    ''
)
content = content.replace(
    '            r"(全链路|ods|dwd|dws).*?(搭建|创建|建)",\n',
    ''
)

with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Removed overly broad patterns')

# Verify
try:
    with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
        compile(f.read(), 'templates.py', 'exec')
    print('Compiles OK')
except SyntaxError as e:
    print(f'Syntax error: {e}')

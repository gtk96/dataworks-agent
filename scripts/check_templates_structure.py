"""Check templates.py structure"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    content = f.read()

# Check what keys exist
import ast

try:
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'INTENT_TEMPLATES':
                    print('INTENT_TEMPLATES found')
                    # Try to evaluate it
                    templates = eval(compile(node, '<string>', 'eval'))
                    print(f'Keys: {list(templates.keys())}')
except Exception as e:
    print(f'AST error: {e}')

# Check if greeting is in the file
print(f'\ngreeting in file: {"greeting" in content}')
print(f'any_ods_modeling in file: {"any_ods_modeling" in content}')

# Show the beginning of INTENT_TEMPLATES
idx = content.find('INTENT_TEMPLATES')
if idx >= 0:
    print('\nAround INTENT_TEMPLATES:')
    print(content[idx:idx+500])

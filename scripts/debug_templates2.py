"""Debug: check templates.py more carefully"""
import re

with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find forward_modeling block
fm_start = content.find('"forward_modeling"')
if fm_start < 0:
    print('ERROR: forward_modeling not found')
    exit(1)

# Find the closing brace of forward_modeling
brace_count = 0
started = False
end_idx = fm_start
for i, c in enumerate(content[fm_start:], fm_start):
    if c == '{':
        brace_count += 1
        started = True
    elif c == '}':
        brace_count -= 1
        if started and brace_count == 0:
            end_idx = i
            break

print(f'forward_modeling starts at {fm_start}, ends at {end_idx}')
print(f'Character at end_idx: {repr(content[end_idx])}')
print(f'Context around end: {repr(content[end_idx:end_idx+50])}')

# Now check if any_ods_modeling was inserted
if '"any_ods_modeling"' in content:
    print('any_ods_modeling found')
    aom = content.find('"any_ods_modeling"')
    print(f'any_ods_modeling at {aom}')
    print(f'Context: {repr(content[aom:aom+100])}')
else:
    print('any_ods_modeling NOT found')

# Check for syntax issues
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'forward_modeling' in line or 'any_ods' in line:
        print(f'Line {i+1}: {repr(line[:100])}')

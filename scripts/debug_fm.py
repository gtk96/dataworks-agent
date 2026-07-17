"""Debug: check forward_modeling block"""
import re

with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find forward_modeling block
fm_start = content.find('"forward_modeling"')
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

# Show the block
block = content[fm_start:end_idx+1]
lines = block.split('\n')
for i, line in enumerate(lines):
    print(f'{i}: {repr(line)}')

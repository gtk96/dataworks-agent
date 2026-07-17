"""Debug: check templates.py"""

with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    content = f.read()

# Count braces
brace_count = 0
for i, c in enumerate(content):
    if c == '{':
        brace_count += 1
    elif c == '}':
        brace_count -= 1
    if brace_count < 0:
        print(f'Unbalanced brace at position {i}')
        print(f'Context: {content[max(0,i-50):i+50]!r}')
        break

# Find forward_modeling
fm = content.find('"forward_modeling"')
if fm >= 0:
    print(f'forward_modeling found at {fm}')
    # Show surrounding context
    start = max(0, fm - 50)
    end = min(len(content), fm + 200)
    print(f'Context: {content[start:end]!r}')
else:
    print('forward_modeling not found')

# Count occurrences
print(f"Total opening braces: {content.count('{')}")
print(f"Total closing braces: {content.count('}')}")

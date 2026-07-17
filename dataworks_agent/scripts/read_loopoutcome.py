import sys

sys.stdout.reconfigure(encoding='utf-8')
with open('dataworks_agent/runtime/shims.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'def to_dict' in line and i > 90:  # skip first to_dict
        print(f"Line {i+1}: {line.rstrip()}")
        for j in range(i+1, min(i+25, len(lines))):
            print(f"Line {j+1}: {lines[j].rstrip()}")
            if lines[j].strip().startswith('def ') and j > i+1:
                break
        break

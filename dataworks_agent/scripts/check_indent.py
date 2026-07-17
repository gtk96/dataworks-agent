import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(588, min(620, len(lines))):
    line = lines[i]
    # Show leading spaces
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    print(f"  {' '*indent}{i+1}: {stripped.rstrip()}")

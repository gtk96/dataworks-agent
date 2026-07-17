import sys

sys.stdout.reconfigure(encoding="utf-8")
with open("dataworks_agent/agent/workflow_service.py", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'result.data["loop"]' in line or "result.data['loop']" in line:
        print(f"Line {i + 1}: {line.rstrip()}")
        # Show surrounding context
        for j in range(max(0, i - 3), min(len(lines), i + 12)):
            marker = ">>>" if j == i else "   "
            print(f"{marker} {j + 1}: {lines[j].rstrip()}")

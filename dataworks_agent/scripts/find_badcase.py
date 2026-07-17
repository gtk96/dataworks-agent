import sys

sys.stdout.reconfigure(encoding="utf-8")
with open("dataworks_agent/agent/workflow_service.py", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "record_badcase" in line:
        for j in range(max(0, i - 2), min(len(lines), i + 15)):
            print(f"{j + 1}: {lines[j].rstrip()}")
        print("---")

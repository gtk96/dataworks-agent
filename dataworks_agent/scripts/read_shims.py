import sys

sys.stdout.reconfigure(encoding="utf-8")
with open("dataworks_agent/runtime/shims.py", encoding="utf-8") as f:
    content = f.read()
idx = content.find("def to_dict")
end = content.find("\n    def ", idx + 10)
if end < 0:
    end = idx + 1000
print(content[idx:end])

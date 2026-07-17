"""Remove patterns 6 and 7 from any_ods_modeling"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find any_ods_modeling block and remove patterns 6 and 7
in_any_ods = False
pattern_count = 0
new_lines = []
skip_next = False

for _i, line in enumerate(lines):
    if '"any_ods_modeling":' in line:
        in_any_ods = True
        new_lines.append(line)
        continue

    if in_any_ods and '"patterns": [' in line:
        new_lines.append(line)
        continue

    if in_any_ods and pattern_count < 10:
        # Skip patterns 6 and 7 (indices 6 and 7)
        if pattern_count in (6, 7):
            pattern_count += 1
            continue
        if line.strip().startswith('r"') or line.strip().startswith("r'"):
            new_lines.append(line)
            pattern_count += 1
            continue

    if in_any_ods and '],' in line and pattern_count >= 8:
        # End of patterns
        new_lines.append(line)
        in_any_ods = False
        continue

    new_lines.append(line)

with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Removed patterns 6 and 7')

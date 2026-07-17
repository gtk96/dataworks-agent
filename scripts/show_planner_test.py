"""Fix test_planner_adds_ods_dwd_steps"""
with open('tests/unit/test_agent_ods_dwd.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show lines 80-95
for i in range(79, 98):
    print(f'{i+1}: {lines[i].rstrip()}')

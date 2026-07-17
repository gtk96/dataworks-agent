"""Check test_chat_agent_full_ods_dwd_flow_collects_artifacts fixture"""
with open('tests/unit/test_agent_ods_dwd.py', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(145, 165):
    print(f'{i+1}: {lines[i].rstrip()}')

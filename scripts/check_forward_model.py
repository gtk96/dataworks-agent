"""Check what _forward_model does with any_ods_modeling"""
with open('dataworks_agent/agent/workflow_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show _forward_model signature and first 20 lines
for i in range(2977, 3010):
    print(f'{i+1}: {lines[i].rstrip()}')

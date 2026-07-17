"""Find where workflow dispatches to specific handlers"""
with open('dataworks_agent/agent/workflow_service.py', encoding='utf-8') as f:
    lines = f.readlines()

# Look for the execute method around line 132
for i in range(130, min(220, len(lines))):
    line = lines[i]
    if any(kw in line for kw in ['forward_modeling', 'ods_dwd', 'agent_workflow', 'execute_once', 'return']):
        print(f'{i+1}: {line.rstrip()}')

"""Show the verify method"""
with open('dataworks_agent/agent/outcome_verifier.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(70, 110):
    print(f'{i+1}: {lines[i].rstrip()}')

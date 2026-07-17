"""Show any_ods_modeling patterns"""
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES

for i, p in enumerate(INTENT_TEMPLATES["any_ods_modeling"]["patterns"]):
    print(f'{i}: {p}')

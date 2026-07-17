"""Add SmartChatPage and ModelingWizard routes"""
with open('frontend/src/router/index.ts', encoding='utf-8') as f:
    content = f.read()

# Replace AgentChatPage with SmartChatPage as the default
content = content.replace(
    "component: () => import('@/pages/AgentChatPage.vue')",
    "component: () => import('@/pages/SmartChatPage.vue')"
)

# Add modeling route
modeling_route = """  { path: 'modeling', name: 'ModelingWizard', component: () => import('@/pages/ModelingWizardPage.vue') },
"""
# Insert before the closing bracket of coreChildren
core_end = content.find("]" , content.find("const coreChildren"))
if core_end > 0:
    content = content[:core_end] + modeling_route + content[core_end:]

with open('frontend/src/router/index.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS')

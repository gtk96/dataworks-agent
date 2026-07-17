"""Update MainLayout with new navigation items"""
with open('frontend/src/layouts/MainLayout.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Add modeling route to advancedItems
if "'/modeling'" not in content:
    content = content.replace(
        "path: '/anomaly', title: '异常排查'",
        "path: '/modeling', title: '全链路建模', iconPath: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },\n          { path: '/anomaly', title: '异常排查'"
    )
    with open('frontend/src/layouts/MainLayout.vue', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: added modeling nav item')
else:
    print('Already has modeling nav item')

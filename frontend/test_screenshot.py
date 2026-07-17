from playwright.sync_api import sync_playwright
import traceback

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        
        # 访问任务列表页面
        print("Navigating to tasks page...")
        page.goto('http://localhost:5173/tasks')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        
        # 截图
        print("Taking screenshot of tasks page...")
        page.screenshot(path='E:/giikin_dw_agent/frontend/screenshot_tasks.png', full_page=True)
        print("Tasks screenshot saved!")
        
        browser.close()
        print("Done!")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()

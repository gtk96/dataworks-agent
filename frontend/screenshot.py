from playwright.sync_api import sync_playwright
import os

os.makedirs('E:/giikin_dw_agent/frontend/screenshots', exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    # 首页/会话页
    print("Capturing home page...")
    page.goto('http://localhost:5173/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/01_home.png', full_page=False)
    print("Home page saved")
    
    # 任务列表
    print("Capturing tasks page...")
    page.goto('http://localhost:5173/tasks')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/02_tasks.png', full_page=False)
    print("Tasks page saved")
    
    # 建模工作台
    print("Capturing modeling page...")
    page.goto('http://localhost:5173/tasks/create')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/03_modeling.png', full_page=False)
    print("Modeling page saved")
    
    # 产物中心
    print("Capturing artifacts page...")
    page.goto('http://localhost:5173/artifacts')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/04_artifacts.png', full_page=False)
    print("Artifacts page saved")
    
    browser.close()
    print("All screenshots saved!")

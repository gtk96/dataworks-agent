from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    # 访问首页
    print("Opening agent chat page...")
    page.goto('http://localhost:5173/')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    
    # 第一条消息：你好
    print("Sending: 你好")
    textarea = page.locator('textarea')
    textarea.fill('你好')
    textarea.press('Enter')
    page.wait_for_timeout(3000)
    
    # 截图
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/conv_01_hello.png', full_page=False)
    print("Screenshot 1 saved")
    
    # 第二条消息：查询订单表
    print("Sending: 查询订单表")
    textarea.fill('查询订单表')
    textarea.press('Enter')
    page.wait_for_timeout(3000)
    
    # 截图
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/conv_02_query.png', full_page=False)
    print("Screenshot 2 saved")
    
    # 第三条消息：再详细一点
    print("Sending: 具体是哪个表")
    textarea.fill('具体是哪个表')
    textarea.press('Enter')
    page.wait_for_timeout(3000)
    
    # 截图
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/conv_03_followup.png', full_page=False)
    print("Screenshot 3 saved")
    
    # 刷新页面测试历史恢复
    print("Refreshing page...")
    page.reload()
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(3000)
    
    # 截图
    page.screenshot(path='E:/giikin_dw_agent/frontend/screenshots/conv_04_refresh.png', full_page=False)
    print("Screenshot 4 saved (after refresh)")
    
    browser.close()
    print("All conversation tests completed!")

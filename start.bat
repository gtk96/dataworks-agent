@echo off
REM dataworks-agent 启动脚本
REM 功能: 端口检查 → 启动 Chrome → 启动 uvicorn

echo === dataworks-agent v0.1.0 ===

REM 0. 检查端口占用
echo [1/4] 检查端口占用...
netstat -ano | findstr :8085 >nul 2>&1
if %errorlevel%==0 (
    echo 端口 8085 已被占用
    set /p confirm="是否终止占用进程? (Y/N): "
    if /i "%confirm%"=="Y" (
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8085') do taskkill /F /PID %%a 2>nul
        echo 已终止占用进程
    ) else (
        echo 请先停止占用端口的进程
        pause
        exit /b 1
    )
)

REM 1. 检查 Chrome
REM 启动 Chrome 时打开 DataWorks IDE；具体 defaultProjectId 从 .env 读取
REM 本地开发者请把 DATAWORKS_PROJECT_ID 填入 .env
if defined DATAWORKS_PROJECT_ID (
    set "DW_IDE_URL=https://dataworks.data.aliyun.com/cn-shenzhen/ide?defaultProjectId=%DATAWORKS_PROJECT_ID%"
) else (
    set "DW_IDE_URL=https://dataworks.data.aliyun.com/cn-shenzhen/ide"
)
echo [2/4] 检查 Chrome :9222...
curl -s http://localhost:9222/json/version >nul 2>&1
if %errorlevel%==1 (
    echo Chrome 未运行，正在启动...
    where chrome.exe >nul 2>&1
    if %errorlevel%==0 (
        start "" "chrome.exe" ^
            --remote-debugging-port=9222 ^
            --user-data-dir=C:\chrome-debug-profile ^
            %DW_IDE_URL%
    ) else (
        start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
            --remote-debugging-port=9222 ^
            --user-data-dir=C:\chrome-debug-profile ^
            %DW_IDE_URL%
    )
    timeout /t 5 /nobreak >nul
) else (
    echo Chrome :9222 已运行
)

REM 2. 确保 data/log 目录存在
if not exist "data" mkdir data
if not exist "log" mkdir log

REM 3. 启动 uvicorn
echo [3/4] 启动 uvicorn :8085...
uv run python -m dataworks_agent.main

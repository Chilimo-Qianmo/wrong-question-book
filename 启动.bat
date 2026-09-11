@echo off
chcp 65001 >nul
title 学生错题集生成器 v2
cd /d "%~dp0"

echo.
echo ============================================
echo   学生错题集生成器 v2
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+ 并勾选 Add Python to PATH。
    pause
    exit /b 1
)

REM 依赖检查：缺什么装什么（首次需要联网）
python -c "import fastapi, uvicorn, pdfplumber, pypdfium2, rapidocr_onnxruntime, onnxruntime, openpyxl, docx, PIL, cv2" >nul 2>nul
if errorlevel 1 (
    echo 正在安装依赖（首次需要联网，请稍候）...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

REM 前端未构建时自动构建（需要 Node.js；已构建则跳过）
if not exist "web\dist\index.html" (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [提示] 未检测到 Node.js，且前端尚未构建，界面将无法打开。
        echo        请安装 Node.js 后在本目录执行： cd web ^&^& npm install ^&^& npm run build
        pause
        exit /b 1
    )
    echo 正在构建前端界面（首次需要联网，约 1 分钟）...
    pushd web
    call npm install --no-fund --no-audit
    call npm run build
    popd
)

echo 正在启动...
python -m app.launcher
if errorlevel 1 pause

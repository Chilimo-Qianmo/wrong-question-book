@echo off
chcp 65001 >nul
title 学生错题集生成器
cd /d "%~dp0"

echo.
echo ============================================
echo   学生错题集生成器（图形界面版）
echo ============================================
echo.

REM =========================================================
REM  检查 Python（需要 3.9+，安装时请勾选“Add Python to PATH”）
REM =========================================================
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9 或更高版本。
    echo 下载地址：https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

REM =========================================================
REM  检查依赖，缺失则自动安装（首次需要联网）
REM =========================================================
REM  依赖：界面(customtkinter) / OCR(rapidocr_onnxruntime + onnxruntime + opencv)
REM        渲染PDF(pypdfium2) / Word(docx) / Excel(openpyxl) / 图片(PIL)
python -c "import customtkinter, pypdfium2, rapidocr_onnxruntime, onnxruntime, openpyxl, docx, PIL" >nul 2>nul
if errorlevel 1 (
    echo 正在检查并安装所需组件（首次需要联网，请稍候）...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install customtkinter pypdfium2 rapidocr_onnxruntime onnxruntime openpyxl python-docx pillow
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试，或手动执行：
        echo   python -m pip install customtkinter pypdfium2 rapidocr_onnxruntime onnxruntime openpyxl python-docx pillow
        pause
        exit /b 1
    )
)

echo 正在启动图形界面...
python "%~dp0错题集生成器.py"
if errorlevel 1 pause

@echo off
chcp 65001 >nul
title 打包学生错题集生成器为EXE
cd /d "%~dp0"

echo.
echo ============================================
echo   将「学生错题集生成器」打包为 EXE
echo   （双击即可，自动安装依赖并打包）
echo ============================================
echo.

REM =========================================================
REM  检查 Python（打包需要 python + pip）
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
REM  安装（或升级）打包工具与运行依赖（首次需要联网）
REM =========================================================
echo 正在检查并安装打包工具与依赖（首次需要联网，请稍候）...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install pyinstaller customtkinter pypdfium2 rapidocr_onnxruntime onnxruntime openpyxl python-docx pillow
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo.
echo 正在打包（约 5-10 分钟，请勿关闭窗口）...
echo.

REM =========================================================
REM  PyInstaller 打包参数（想改打包方式就改这里，已加注释）：
REM   --onefile     打成单个 EXE，便于分发
REM   --windowed    图形界面程序，运行时不弹黑窗口
REM   --name        EXE 名称
REM   --collect-all <包>   把 OCR/PDF 库的 数据+模块 全部打进 EXE
REM   --hidden-import 生成错题集   显式包含核心模块
REM   --add-binary  "DLL;."  补齐 onnxruntime 所需 VC/OpenMP 运行库 DLL（否则报“DLL 初始化失败”）
REM   --exclude-module 剔除用不到的重型依赖，显著减小体积
REM =========================================================
pyinstaller --noconfirm --clean --onefile --windowed --name 错题集生成器 ^
  --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pypdfium2 ^
  --hidden-import 生成错题集 ^
  --add-binary "C:\Windows\System32\vcruntime140.dll;." ^
  --add-binary "C:\Windows\System32\vcruntime140_1.dll;." ^
  --add-binary "C:\Windows\System32\msvcp140.dll;." ^
  --add-binary "C:\Windows\System32\vcomp140.dll;." ^
  --add-binary "C:\Windows\System32\concrt140.dll;." ^
  --exclude-module pandas --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module qtpy ^
  --exclude-module PySide2 --exclude-module PySide6 --exclude-module dask --exclude-module distributed ^
  --exclude-module numba --exclude-module llvmlite --exclude-module xarray --exclude-module bokeh ^
  --exclude-module holoviews --exclude-module plotly --exclude-module sqlalchemy --exclude-module tables ^
  --exclude-module botocore --exclude-module boto3 --exclude-module s3fs --exclude-module fsspec ^
  --exclude-module lz4 --exclude-module cloudpickle --exclude-module matplotlib --exclude-module scipy ^
  --exclude-module seaborn --exclude-module zarr --exclude-module h5py ^
  "%~dp0错题集生成器.py"

if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo [成功] 打包完成！EXE 位于：
echo   %~dp0dist\错题集生成器.exe
echo 发布时请把 exe 与「题目配置.json」「图片」文件夹放在同一目录。
echo.
pause

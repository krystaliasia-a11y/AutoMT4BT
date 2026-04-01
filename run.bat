@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "config.yaml" (
    echo [錯誤] config.yaml 不存在，請先執行 install.bat
    pause
    exit /b 1
)

:: 偵測 Python 位置：優先用內嵌式，其次用 venv，最後用系統
set "PYTHON_CMD="

if exist "python\python.exe" (
    set "PYTHON_CMD=%~dp0python\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if "!PYTHON_CMD!"=="" (
    echo [錯誤] 找不到 Python，請先執行 install.bat
    pause
    exit /b 1
)

echo ============================================================
echo   AutoMT4BT 自動回測系統
echo ============================================================
echo.

"!PYTHON_CMD!" main.py

echo.
echo 回測結束。
pause

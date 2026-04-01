@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================================
echo   AutoMT4BT 自動回測系統 - 一鍵安裝
echo ============================================================
echo.

:: ============================================================
:: 1. 檢查 Python（找不到就自動下載內嵌式 Python）
:: ============================================================
echo [1/5] 檢查 Python...

set "EMBEDDED_PYTHON=%~dp0python\python.exe"
set "USE_EMBEDDED=0"

:: 優先檢查系統 Python
python --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
    echo        系統 Python %PYVER% OK
    set "PYTHON_CMD=python"
    goto :python_ok
)

:: 檢查是否已有內嵌式 Python
if exist "!EMBEDDED_PYTHON!" (
    for /f "tokens=2 delims= " %%v in ('"!EMBEDDED_PYTHON!" --version 2^>^&1') do set PYVER=%%v
    echo        內嵌式 Python %PYVER% OK
    set "PYTHON_CMD=!EMBEDDED_PYTHON!"
    set "USE_EMBEDDED=1"
    goto :python_ok
)

:: 都沒有，自動下載內嵌式 Python
echo        找不到 Python，正在下載內嵌式 Python 3.12...
echo.

set "PY_URL=https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
set "PY_ZIP=%~dp0python_embed.zip"
set "PY_DIR=%~dp0python"

:: 使用 PowerShell 下載
powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' }" 2>nul
if not exist "!PY_ZIP!" (
    echo [錯誤] 下載 Python 失敗，請確認網路連線
    echo        或手動下載 Python 3.10+ 並安裝：https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 解壓縮
echo        解壓縮中...
if not exist "!PY_DIR!" mkdir "!PY_DIR!"
powershell -Command "& { Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force }" 2>nul
del "!PY_ZIP!" >nul 2>&1

if not exist "!EMBEDDED_PYTHON!" (
    echo [錯誤] 解壓縮失敗
    pause
    exit /b 1
)

:: 啟用 import 機制：修改 python312._pth，取消 import site 的註解
set "PTH_FILE=!PY_DIR!\python312._pth"
if exist "!PTH_FILE!" (
    powershell -Command "& { (Get-Content '!PTH_FILE!') -replace '#import site','import site' | Set-Content '!PTH_FILE!' }"
)

:: 下載並安裝 pip
echo        安裝 pip...
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "GET_PIP=%~dp0get-pip.py"
powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%' }" 2>nul
"!EMBEDDED_PYTHON!" "!GET_PIP!" --no-warn-script-location >nul 2>&1
del "!GET_PIP!" >nul 2>&1

for /f "tokens=2 delims= " %%v in ('"!EMBEDDED_PYTHON!" --version 2^>^&1') do set PYVER=%%v
echo        內嵌式 Python %PYVER% 安裝完成
set "PYTHON_CMD=!EMBEDDED_PYTHON!"
set "USE_EMBEDDED=1"

:python_ok

:: ============================================================
:: 2. 輸入 MT4 安裝路徑
:: ============================================================
echo.
echo [2/5] 設定 MT4 安裝路徑...
echo        請輸入 MT4 安裝路徑（含 terminal.exe 的資料夾）
echo        例如：C:\Program Files (x86)\MetaTrader 4 IC Markets Global
echo.
set /p "MT4_PATH=MT4 安裝路徑: "

if "!MT4_PATH!"=="" (
    echo [錯誤] 路徑不能為空
    pause
    exit /b 1
)
if not exist "!MT4_PATH!\terminal.exe" (
    echo [錯誤] 找不到 terminal.exe，路徑無效：!MT4_PATH!
    pause
    exit /b 1
)
echo        OK：!MT4_PATH!

:: ============================================================
:: 3. 輸入 MT4 Data Directory
:: ============================================================
echo.
echo [3/5] 設定 MT4 資料目錄...
echo        通常在：%APPDATA%\MetaQuotes\Terminal\[HASH]
echo        找法：MT4 ^> File ^> Open Data Folder，複製該路徑
echo.

:: 列出已存在的 terminal hash 目錄供參考
set "APPDATA_MT4=%APPDATA%\MetaQuotes\Terminal"
if exist "%APPDATA_MT4%" (
    echo        偵測到以下資料目錄：
    for /d %%h in ("%APPDATA_MT4%\*") do (
        echo          %%h
    )
    echo.
)

set /p "MT4_DATA=MT4 資料目錄: "

if "!MT4_DATA!"=="" (
    echo [錯誤] 路徑不能為空
    pause
    exit /b 1
)
if not exist "!MT4_DATA!" (
    echo [錯誤] 目錄不存在：!MT4_DATA!
    pause
    exit /b 1
)
echo        OK：!MT4_DATA!

:: ============================================================
:: 4. 安裝 Python 依賴
:: ============================================================
echo.
echo [4/5] 安裝 Python 依賴...

cd /d "%~dp0"

if "!USE_EMBEDDED!"=="1" (
    :: 內嵌式 Python：直接安裝到內嵌目錄
    "!PYTHON_CMD!" -m pip install -r requirements.txt --quiet --no-warn-script-location
    if errorlevel 1 (
        echo [錯誤] 安裝依賴失敗
        pause
        exit /b 1
    )
) else (
    :: 系統 Python：使用 venv
    if not exist "venv" (
        python -m venv venv
        echo        虛擬環境已建立
    ) else (
        echo        虛擬環境已存在，跳過
    )
    call venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo [錯誤] 安裝依賴失敗
        pause
        exit /b 1
    )
)
echo        依賴安裝完成

:: ============================================================
:: 5. 產生 config.yaml
:: ============================================================
echo.
echo [5/5] 產生設定檔 config.yaml...

:: 將路徑中的 \ 轉為 \\ 給 YAML 用
set "MT4_PATH_ESC=!MT4_PATH:\=\\!"
set "MT4_DATA_ESC=!MT4_DATA:\=\\!"

(
echo mt4:
echo   terminal_path: "!MT4_PATH_ESC!\\terminal.exe"
echo   data_dir: "!MT4_DATA_ESC!"
echo.
echo backtest:
echo   expert: "MACD_Sample.ex4"
echo   symbol: "EURUSD"
echo   period: "H1"
echo   model: 0               # 0=Every Tick, 1=Control Points, 2=Open Prices Only
echo   from_date: "2026.02.01"
echo   to_date: "2026.03.01"
echo   deposit: 10000
echo   currency: "USD"
echo   leverage: 100
echo.
echo paths:
echo   settings_dir: "settings"
echo   results_dir: "results"
echo   reports_subdir: "reports"
echo   excel_filename: "backtest_results.xlsx"
echo.
echo runner:
echo   timeout: 300            # 單次回測超時（秒）
echo   cooldown: 5             # 回測間隔等待（秒）
echo   kill_before_run: true   # 回測前是否強制關閉已開啟的 MT4
) > config.yaml

echo        config.yaml 已產生

:: ============================================================
:: 建立必要目錄
:: ============================================================
if not exist "settings" mkdir settings
if not exist "results\reports" mkdir "results\reports"

:: ============================================================
:: 完成
:: ============================================================
echo.
echo ============================================================
echo   安裝完成！
echo ============================================================
echo.
echo   MT4 路徑：!MT4_PATH!
echo   資料目錄：!MT4_DATA!
echo.
echo   使用方式：
echo     1. 將 .set 檔案放入 settings\ 目錄
echo     2. 編輯 config.yaml 設定 EA 名稱、幣對、日期等
echo     3. 雙擊 run.bat 開始回測
echo.
echo   輸出：
echo     results\backtest_results.xlsx  （回測結果 Excel）
echo     results\reports\              （HTML 報告）
echo ============================================================
echo.
pause

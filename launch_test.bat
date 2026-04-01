@echo off
echo Killing MT4...
taskkill /f /im terminal.exe >nul 2>&1
timeout /t 3 /nobreak >nul

echo Launching MT4 with config...
"C:\Program Files (x86)\MetaTrader 4 IC Markets Global\terminal.exe" "C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\5D49F47D1EA1ECFC0DDC965B6D100AC5\backtest_auto.ini"

echo MT4 exited with code: %ERRORLEVEL%
pause

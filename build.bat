@echo off
REM Build script for StockMarketAI — creates trading.exe

setlocal enabledelayedexpansion

echo [BUILD] Activating venv...
call .venv\Scripts\activate.bat

echo [BUILD] Installing PyInstaller...
pip install pyinstaller -q

echo.
echo [BUILD] Building trading.exe (terminal)...
pyinstaller build_terminal.spec --distpath . --clean

if exist trading\trading.exe (
    echo [BUILD] ✓ trading.exe created in .\trading\
) else (
    echo [BUILD] ✗ FAILED — check errors above
    exit /b 1
)

echo.
echo [BUILD] ✓ Done!
echo.
echo   Run terminal:  .\trading\trading.exe
echo   Run backtest:  python backtest.py
echo.
echo   Required env vars:
echo     set T212_API_KEY=xxx
echo     set T212_SECRET_KEY=xxx
echo.

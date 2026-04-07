@echo off
REM Build trading.exe — PySide6 desktop app
call .venv\Scripts\activate.bat
pyinstaller trading.spec --clean
if exist dist\blank.exe (
    echo.
    echo   Done: dist\blank.exe
) else (
    echo   FAILED — check errors above
    exit /b 1
)

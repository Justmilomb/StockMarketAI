@echo off
if not exist .venv (
    echo Virtual environment not found. Running setup.bat...
    call setup.bat
)

echo Activating virtual environment...
call .venv\Scripts\activate

if "%GEMINI_API_KEY%"=="" (
    echo WARNING: GEMINI_API_KEY environment variable is not set!
    echo The AI features will fail.
    echo.
    echo Please set it using: 
    echo   [System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "YOUR_KEY", "User")
    echo.
    pause
)

echo Starting Trading Terminal...
python terminal/app.py
pause

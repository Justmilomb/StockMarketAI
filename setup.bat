@echo off
echo.
echo [1/3] Creating virtual environment...
python -m venv .venv

echo [2/3] Activating virtual environment and installing dependencies...
call .venv\Scripts\activate
pip install -r requirements-desktop.txt

echo.
echo [3/3] Setup complete!
echo To start the terminal app, use: run.bat
echo.
pause

@echo off
REM Build blank.exe — PySide6 desktop app + installer
call .venv\Scripts\activate.bat

REM === Step 1: PyInstaller ===
echo Building blank.exe...
pyinstaller trading.spec --clean
if not exist dist\blank.exe (
    echo   FAILED — check errors above
    exit /b 1
)
echo   Done: dist\blank.exe

REM === Step 2: Code signing (when certificate is available) ===
if defined BLANK_CERT_PATH (
    echo Signing dist\blank.exe...
    signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank.exe
    if errorlevel 1 (
        echo   WARNING: Code signing failed
    ) else (
        echo   Signed successfully
    )
) else (
    echo   Skipping code signing (BLANK_CERT_PATH not set)
)

REM === Step 3: Inno Setup installer ===
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    echo Building BlankSetup.exe...
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\blank.iss
    if defined BLANK_CERT_PATH (
        echo Signing dist\BlankSetup.exe...
        signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\BlankSetup.exe
    )
) else (
    echo   Inno Setup not found — skipping installer build
)

echo.
echo   Build complete.

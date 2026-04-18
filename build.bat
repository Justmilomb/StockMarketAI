@echo off
REM Build blank desktop application
call .venv\Scripts\activate.bat

echo Building blank.exe...
pyinstaller installer\blank.spec --clean
if not exist dist\blank.exe (
    echo   FAILED — check errors above
    exit /b 1
)
echo   Done: dist\blank.exe

REM === Code signing (when certificate is available) ===
if defined BLANK_CERT_PATH (
    echo Signing executable...
    signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank.exe
    echo   Signed
) else (
    echo   Skipping code signing (BLANK_CERT_PATH not set)
)

REM === Inno Setup installer ===
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    echo Building blank-setup.exe...
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\blank.iss
    if defined BLANK_CERT_PATH (
        echo Signing installer...
        signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank-setup.exe
    )
) else (
    echo   Inno Setup not found — skipping installer build
)

echo.
echo   Build complete.

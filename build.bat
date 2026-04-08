@echo off
REM Build Blank Bloomberg + Simple editions
call .venv\Scripts\activate.bat

REM === Bloomberg edition ===
echo [1/2] Building blank-bloomberg.exe...
pyinstaller installer\bloomberg.spec --clean
if not exist dist\blank-bloomberg.exe (
    echo   FAILED — check errors above
    exit /b 1
)
echo   Done: dist\blank-bloomberg.exe

REM === Simple edition ===
echo [2/2] Building blank-simple.exe...
pyinstaller installer\simple.spec --clean
if not exist dist\blank-simple.exe (
    echo   FAILED — check errors above
    exit /b 1
)
echo   Done: dist\blank-simple.exe

REM === Code signing (when certificate is available) ===
if defined BLANK_CERT_PATH (
    echo Signing executables...
    signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank-bloomberg.exe
    signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank-simple.exe
    echo   Signed
) else (
    echo   Skipping code signing (BLANK_CERT_PATH not set)
)

REM === Inno Setup installers ===
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    echo Building BlankBloombergSetup.exe...
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\bloomberg.iss
    echo Building BlankSimpleSetup.exe...
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\simple.iss
    if defined BLANK_CERT_PATH (
        echo Signing installers...
        signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\BlankBloombergSetup.exe
        signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\BlankSimpleSetup.exe
    )
) else (
    echo   Inno Setup not found — skipping installer build
)

echo.
echo   Build complete.

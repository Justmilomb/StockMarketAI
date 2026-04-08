@echo off
title Blank
cd /d "%~dp0"
if exist dist\blank-bloomberg.exe (
    dist\blank-bloomberg.exe
) else if exist dist\blank-simple.exe (
    dist\blank-simple.exe
) else (
    echo No built executable found. Run build.bat first.
)
pause

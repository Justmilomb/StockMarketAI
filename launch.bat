@echo off
title blank
cd /d "%~dp0"
if exist dist\blank.exe (
    dist\blank.exe
) else (
    echo No built executable found. Run build.bat first.
)
pause

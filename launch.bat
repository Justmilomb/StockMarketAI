@echo off
title StockMarketAI Trading Terminal
mode con: cols=200 lines=55
color 0E
cd /d "%~dp0"
trading.exe
pause
